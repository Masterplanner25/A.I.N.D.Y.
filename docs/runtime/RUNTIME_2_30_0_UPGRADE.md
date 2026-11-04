---
title: "Runtime 2.30.0 adoption"
last_verified: "2026-11-04"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.30.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.30.0.md` (tag `v2.30.0`, `7590efa`, #887). No schema
change (head stays `0020`, contract `2026-09-20`), no dependency-pin change, no ui-kit release (2.1.1
stays). We come from 2.29.2 (live since 2026-11-04 05:13:18Z, `RUNTIME_2_29_2_UPGRADE.md`).

**Released through A.I.N.D.Y.** Handoff `36d9f917`, requested 05:56:48Z on 2026-11-04. The gate email
went out at 06:08:29Z. The owner replied APPROVE by email at 06:09Z, and **the watcher missed the
reply**: Gmail's IMAP `SINCE` compares the account's local date (Pacific, still 11-03), and we passed
the UTC date (11-04). Fixed in #535, which goes live with this rebuild. The owner then approved on the
Collaborator card at 06:24:13Z, and the handoff was `done` at 06:26:19Z.

## 1. Own-session recall defaults on (#885, DEC-106)

No change here: `.env` sets `AINDY_MEMORY_RECALL_OWN_SESSION=true`, and compose passes it through
(`"${AINDY_MEMORY_RECALL_OWN_SESSION:-}"`, where a blank value now also means on). We keep the line.

**The `StaticPool` note:** our `tests/fixtures/db.py` builds the SQLite `db_session` on one
`StaticPool` connection, which is the shape the handoff warns about. The CI suite on this PR is the
check. If rows vanish after a recall in a test, this is the first thing to look at.

## 2. Closing the stranded units (#886, DEC-107)

Recounted before the rebuild (2026-11-04, 2.29.2 container): **2,387** units `pending` whose
`job_logs` row is `failed`, and all 2,387 carry exactly *"Stale: never started within 1 hour of
creation"*, so the command's filter should take every one. `--yes` writes the owner's database, so it
is the owner's call.

## 3. The Postgres JSON filter

Proven in the runtime's CI (`test_job_log_settle_postgres.py`). Nothing to do here.

## 4. Done here

- **Pin and floor together:** `constraints.txt` `==2.30.0` and `pyproject.toml`
  `aindy-runtime[mcp,security]>=2.30.0,<3.0`, plus the contract test and CLAUDE.md.

## 5. Rebuild and settle

Owed after this PR merges. Before the recreate, read `aindy_payload_identity_mismatch_total`
(window 10, open since 05:13:18Z). After it:

```bash
docker exec <api> python -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
# expect: 2.30.0 ['/usr/local/lib/python3.11/site-packages/AINDY']
docker exec <api> aindy-runtime jobs settle-stale-units        # dry run; expect 2,387
```
