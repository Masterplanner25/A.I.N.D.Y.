"""Find the synthetic leadgen rows written before the fixture gate shipped.

**Read-only. This script never deletes anything.** It reports what exists so the
delete-or-mark decision is made against counts rather than guesses.

Background: `run_ai_search` used to substitute three hardcoded companies whenever
retrieval produced nothing — on an exception *or* on an empty result set. Everything
downstream then ran for real, so the fabricated leads were scored, persisted, and
written to memory. The gate now requires `AINDY_LEADGEN_ALLOW_FIXTURES`, but rows
already written are unaffected by that and keep feeding recall.

Usage:
    python scripts/audit_leadgen_fixtures.py
    python scripts/audit_leadgen_fixtures.py --since 2026-08-17T00:00:00

The three fixtures are hardcoded constants, which is the one piece of luck here — they
are exactly identifiable, with no heuristics.

**Matched on URL, not company name.** A real company could plausibly be called
"Acme AI Solutions"; the URL triple is the stronger key. Company is reported as a
secondary signal so a mismatch between the two counts is visible rather than silent.
"""
from __future__ import annotations

import argparse
import os
import sys

# The URL triple is the primary key for identification. Kept in sync with
# apps/search/services/leadgen_service.py::_DEV_FIXTURE_LEADS, which
# tests/unit/test_leadgen_fixture_gate.py pins.
FIXTURE_URLS = ("https://acmeai.com", "https://finovatelabs.io", "https://healthedge.ai")
FIXTURE_COMPANIES = ("Acme AI Solutions", "Finovate Labs", "HealthEdge Analytics")
FIXTURE_HOSTS = ("acmeai.com", "finovatelabs.io", "healthedge.ai")


def _rows(conn, sql, params=None):
    from sqlalchemy import text

    return conn.execute(text(sql), params or {}).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default=None,
        help="ISO timestamp of the fixture-gate deploy. Rows at or after it are a FINDING: "
             "they mean AINDY_LEADGEN_ALLOW_FIXTURES was set somewhere it should not be.",
    )
    args = parser.parse_args()

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2

    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    params = {"urls": list(FIXTURE_URLS), "companies": list(FIXTURE_COMPANIES)}
    findings = 0

    with engine.connect() as conn:
        print("=" * 72)
        print("LEADGEN FIXTURE AUDIT (read-only)")
        print("=" * 72)

        # ── 1. lead_actions FIRST ────────────────────────────────────────────
        # Deliberately before leadgen_results: lead_actions.leadgen_result_id is
        # ON DELETE SET NULL, so deleting the lead rows first ORPHANS these actions
        # rather than removing them, and an orphaned action is harder to interpret
        # than a linked one. Note the table is `lead_actions`, plural.
        print("\n[1] lead_actions — downstream consequences (resolve these FIRST)")
        rows = _rows(conn, """
            SELECT la.id, la.leadgen_result_id, lr.company, lr.url
            FROM lead_actions la
            JOIN leadgen_results lr ON lr.id = la.leadgen_result_id
            WHERE lr.url = ANY(:urls) OR lr.company = ANY(:companies)
            ORDER BY la.id
        """, params)
        print(f"    actions drafted against fixture leads: {len(rows)}")
        for r in rows[:10]:
            print(f"      action={r[0]}  lead={r[1]}  {r[2]} ({r[3]})")
        findings += len(rows)

        # ── 2. leadgen_results ───────────────────────────────────────────────
        print("\n[2] leadgen_results — the rows")
        by_url = _rows(conn, """
            SELECT count(*) FROM leadgen_results WHERE url = ANY(:urls)
        """, params)[0][0]
        by_company = _rows(conn, """
            SELECT count(*) FROM leadgen_results WHERE company = ANY(:companies)
        """, params)[0][0]
        print(f"    matched by URL (primary key):     {by_url}")
        print(f"    matched by company (secondary):   {by_company}")
        if by_company != by_url:
            print("    ** counts differ — inspect before acting. A company-only match may be a")
            print("       real company sharing a fixture name; a URL-only match should not happen.")
        findings += by_url

        # ── 3. memory_nodes, two distinct shapes ─────────────────────────────
        print("\n[3] memory_nodes — per-lead nodes ('Lead Discovered: ...')")
        per_lead = _rows(conn, """
            SELECT count(*) FROM memory_nodes
            WHERE content LIKE 'Lead Discovered: Acme AI Solutions%'
               OR content LIKE 'Lead Discovered: Finovate Labs%'
               OR content LIKE 'Lead Discovered: HealthEdge Analytics%'
        """)[0][0]
        print(f"    per-lead memory nodes: {per_lead}")
        findings += per_lead

        # These are the ones that matter most and are the easiest to miss.
        # run_ai_search calls MemoryOrchestrator.get_context(tags=[leadgen, search,
        # outcome]) at the top of EVERY subsequent run, so a fabricated outcome node is
        # recalled as prior experience on future real searches. The contamination is not
        # static — it feeds forward.
        print("\n[4] memory_nodes — per-search OUTCOME nodes (these feed forward)")
        outcome = _rows(conn, """
            SELECT count(*) FROM memory_nodes
            WHERE source = 'leadgen_search'
              AND (content LIKE '%Top result: Acme AI Solutions'
                OR content LIKE '%Top result: Finovate Labs'
                OR content LIKE '%Top result: HealthEdge Analytics')
        """)[0][0]
        print(f"    outcome nodes recalled as prior context: {outcome}")
        if outcome:
            print("    ** these are recalled on every later leadgen search — highest priority")
        findings += outcome

        # ── 4. cascade check before anyone deletes ───────────────────────────
        print("\n[5] cascade surface (memory_node_history / memory_trace_nodes)")
        for tbl, col in (("memory_node_history", "node_id"), ("memory_trace_nodes", "node_id")):
            try:
                n = _rows(conn, f"""
                    SELECT count(*) FROM {tbl} t
                    JOIN memory_nodes m ON m.id = t.{col}
                    WHERE m.content LIKE 'Lead Discovered:%%'
                       OR (m.source = 'leadgen_search' AND m.content LIKE '%%Top result:%%')
                """)[0][0]
                print(f"    {tbl}: {n} rows reference candidate nodes (ON DELETE CASCADE)")
            except Exception as exc:  # column names differ across versions; report, do not fail
                print(f"    {tbl}: could not check ({type(exc).__name__}) — verify manually")

        # ── 5. date bounding ─────────────────────────────────────────────────
        if args.since:
            print(f"\n[6] rows at or after {args.since} — any hit is itself a finding")
            after = _rows(conn, """
                SELECT count(*) FROM leadgen_results
                WHERE url = ANY(:urls) AND created_at >= :since
            """, {**params, "since": args.since})[0][0]
            print(f"    fixture rows written after the gate shipped: {after}")
            if after:
                print("    ** AINDY_LEADGEN_ALLOW_FIXTURES is set somewhere it should not be.")

        print("\n" + "=" * 72)
        print(f"TOTAL candidate rows across all tables: {findings}")
        print("Nothing was deleted. Resolve lead_actions before leadgen_results.")
        print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
