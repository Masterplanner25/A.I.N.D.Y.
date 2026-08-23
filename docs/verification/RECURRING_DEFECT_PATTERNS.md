---
title: "Recurring Defect Patterns — the shapes this repo produces"
last_verified: "2026-08-22"
api_version: "1.0"
status: current
owner: "app-team"
---

# Recurring Defect Patterns

Defects in this repo are not random. Six shapes account for most of what live verification has
found, and each has a cheap diagnostic that beats reading code. This document exists because these
patterns were recorded only in session handoffs — the owner's local working notes, which are
gitignored and therefore invisible to everyone else. They were extracted here on 2026-08-22 when
those handoffs were consolidated.

**Read the diagnostics before the code.** Every one of these was found faster by a probe than by
inspection, and several were *missed* by inspection.

---

## 1. Dead twins — a working engine beside a dead duplicate wired to the nav

The dominant shape. A capability exists twice: a general, system-fed version that works, and an
earlier personal or manual version that is the one actually wired to a surface.

| Dead v1 (wired) | Working v2 (built, elsewhere) |
|---|---|
| LinkedIn manual ingest | system-fed social analytics |
| 13 manual KPI calculators | the Infinity score engine |
| `books_required` / `studio` / `playbooks` | `Goal` / `GoalState`, the anchor |
| `/apps/compute/masterplans` | `/apps/masterplans/` |
| ARM's own KPI service | Infinity recomputing the same 3 KPIs |
| `evaluate_phase` ×3, byte-identical | only `projection_service`'s copy is imported |
| runtime-served `/platform/` SPA | this repo's `client/platform.html` (see FR-21) |

**Diagnostic: check whether the table has rows.** `canonical_metrics = 0` exposed three
simultaneous breaks that no amount of code reading had caught. A surface backed by an empty table
is either dead or starved, and the distinction takes one query.

**Before building anything, check whether it already exists elsewhere.** The `/kpi` rewire
(#168) was wiring, not construction: 0 of 13 formulas were auto-sourceable, and the engine that
already computed the real thing was one route away.

---

## 2. Response-shape mismatch — the blank panel with no error

Five defects on five surfaces, ~40 `safeMap prevented crash` lines inside `@aindy/ui-kit`, and 56
references across the walk log. Five instances, five *different* shapes: missing unwrap, collection
nested under a named key (`data.tasks`), blank-render-on-failure, missing unwrap again, and a
partial envelope carrying `data` with no `status`.

**Signature: a blank panel with no error and no empty state.** An object has no `.length`, so the
empty branch does not fire either. Nothing looks broken; nothing renders.

**Root cause is a contract gap, not a client bug.** Only routes that go through the execution
pipeline are enveloped, both shapes share the `/apps/*` URL space, and nothing distinguishes them —
so every consumer must carry per-route knowledge. Filed as **FR-19**. A blanket unwrap is not a
workaround: it corrupts any plain response that legitimately carries a `data` key.

---

## 3. A 4xx raised before pipeline entry becomes an opaque 500 — CLOSED as a class

Four of seven defects in one handoff traced to this. A route raising `HTTPException` *before*
entering the execution pipeline had its status replaced by a `RouteExecutionViolation` (500), so a
stale link 500'd instead of 404'ing — and a deliberate 400 became undiagnosable.

**Status: closed as a class and CI-enforced.** `scripts/check_route_pipeline_contract.py` scans 43
router modules with 0 violations as of 2026-08-22. **FR-20** asks the runtime to preserve the raised
status as well, so the symptom cannot return silently.

**Note the detection lesson:** file-level static analysis cannot find these, because every file that
raises `HTTPException` also uses the pipeline somewhere — the violation is per *route*. The
empirical sweep was the only reliable detector until the guard existed.

---

## 4. Dict-where-object — a public contract converted, a consumer not updated

A domain converts its public contract to dicts (correct for a cross-domain boundary) and a consumer
keeps using attribute access.

- `apps/social/services/linkedin_adapter.py:5` — `raw.likes` on a `model_dump()` dict
- `apps/rippletrace/services/prediction_engine.py` — `thresholds.velocity_trend` on a function
  explicitly typed `-> dict[str, Any]` (since fixed; now `thresholds.get("velocity_trend", …)`)

**The recommended sweep of every `apps/*/public.py` consumer has never been run.** Both known
instances are fixed, so this is a latent shape rather than an open defect — but the sweep is the
only thing that would say so with confidence.

---

## 5. Built to spec, one wire short of a surface

Almost nothing in one whole session was construction. Each of these was built to a written design
and stopped before anything could reach it:

| Built | Missing |
|---|---|
| `mcp-server` (stdio + SSE + allowlist) | the `[mcp]` extra and an app allowlist |
| Watcher → `focus_quality` → Infinity | nothing emits signals |
| `TrustTier`, `engagement_score` | nothing renders them |
| `suggest_tools_for_kpi` | consumed only by the operator console |
| `agents` + `memory_namespace` + capability mappings | no registration API (later FR-12) |
| 210 recorded decisions, per-type expectation models | no surface names them |
| `critical_path`, `topological_order` | unreachable by name |

**Reading the original build doc before writing code was the highest-yield move every time**, and
twice it corrected a wrong inference. The specs were right; the surface layer stopped early.

Its cousin is **built, correct, and switched off**: five features behind default-off flags waiting
on a soak that cannot produce evidence (`SOAK-THEN-FLIP-1`).

---

## 6. The summary row that contradicts its own entry

A document's index says one thing and the entry says another. Readers scan the index.

Confirmed twice on 2026-08-22, hours apart:

- `TECH_DEBT.md` — **seven** items whose bodies said RESOLVED while their headings said nothing.
  Scanning headings suggested 13 open items where there were about 6.
- `FRONTEND_WALK_LOG.md` — item 20's body said **`✅ FIXED (#194)`** while its row in the table
  headed *"Open"* said "hardening recommended". Item 18 had the same mismatch.

**This one has teeth.** Trusting that walk-log table caused a **P1 security item to be filed
against a vulnerability that had been fixed three weeks earlier** (`ARM-PATH-CONFINE-1`, withdrawn
the same day), and a second entry was filed against a route the runtime had since shipped
(`CLIENT-ERROR-TELEMETRY-1`, also withdrawn). Both were filed from summary rows without opening the
entry, in the same session that had already audited this exact defect elsewhere.

**Diagnostic: a summary row is a claim about a document, not the document.** When the status
matters — and a security item is exactly when it matters — read the entry, then verify the entry
against running code. Two of three items filed from that table were already fixed.
