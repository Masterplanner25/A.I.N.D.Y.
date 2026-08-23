---
title: "KPI Dashboard Wiring — /kpi rewired onto the live score engine"
last_verified: "2026-08-22"
api_version: "1.0"
status: outdated
owner: "app-team"
---

# KPI Dashboard Wiring Plan

**Status:** ✅ implemented on `feat/kpi-scores-dashboard` (2026-07-31) · **Owner decisions
captured:** walk-log items 18 & 32 · **Scope:** frontend-only · **Backend changes:** none ·
**Migrations:** none

---

## Why this exists

The walk flagged `/kpi` as *"a manual calculator that was meant to be a dashboard"* (item 18),
and the platform Executions tab as *"13 app-domain Infinity calculators on the operator surface"*
(item 32). Investigation resolved both into a single fact:

**This repo has two parallel KPI systems, and `/kpi` renders the wrong one.**

| System | What it is | State |
|---|---|---|
| **13 `calculate*` panels** (what `/kpi` shows today) | Pure formulas. User types numbers → stateless `/compute` route echoes a result. Inputs are **discarded** (`save_calculation` persists one scalar to `calculation_results`; the typed inputs are thrown away). The 13 input tables in `apps/analytics/metrics_models.py` are **dead schema** — imported only for `Base` registration, never written. | ❌ not a dashboard, can't become one |
| **Infinity scoring engine** (`apps/analytics/services/scoring/infinity_service.py`) | Computes a master score + 5 KPIs from **live system data**, persists to `user_scores` / `score_history`, runs on a daily cron, is already routed. | ✅ live, persisted, self-seeding |

A real system-fed dashboard is therefore a **wiring job on the engine**, not a data-collection
project. The engine is the proof of feasibility; it just doesn't use the 13 formulas.

---

## Data-readiness verdict (why we build on the engine, not the formulas)

Across the 13 manual formulas, **zero are fully sourceable** from automated system data. Grouped
by blocker:

- **No source at all** (would need new instrumentation): IncomeEfficiency, RevenueScaling,
  AttentionValue, ExecutionSpeed (manual), LostPotential. Inputs like `expenses`, `capital`,
  `focused_effort`, `content_output`, `platform_presence`, `systemized_workflows`, `decision_lag`,
  `time_saved`, `missed_opportunities`, `gains_from_action` have no table.
- **Manual-ingest only** (LinkedIn, not a live feed; individual likes/shares/comments are
  collapsed on ingest): Engagement, Impact, EngagementRate, and the audience half of
  MonetizationEfficiency.
- **Partial** (some inputs real, some absent): AIEfficiency, BusinessGrowth,
  MonetizationEfficiency, AIProductivityBoost (manual), DecisionEfficiency (manual).

The real signals cluster around **revenue** (freelance), **AI-usage** (ARM), and
**task/decision counts** (tasks, autonomy) — which is exactly what the engine already reads.

Full per-formula table lives in the session analysis; not duplicated here.

---

## Target design — a `/scores`-backed `/kpi`

### Hero — Master Score
Source: `GET /apps/analytics/scores/me` → `master_score`, `metadata`.

- 0–100 master number + confidence badge (`metadata.confidence`, e.g. `baseline`)
- Provenance line: "As of `{metadata.calculated_at}` · `{metadata.data_points_used}` signals ·
  last updated by `{metadata.trigger_event}`"
- **Recalculate** button → `POST /apps/analytics/scores/recalculate`, then refetch
- Sparkline of `master_score` from `GET /apps/analytics/scores/history?limit=30`,
  bars colored by `score_delta` (up = green, down = red; first sample's delta is null)

### Row A — 5 behavioral KPIs
Source: `scores/me` → `kpis{}`. Scale is 0–50–100 with **50 = neutral baseline** — mark it.

| Tile | Field | One-liner |
|---|---|---|
| Execution Speed | `kpis.execution_speed` | Completion velocity vs. your own baseline |
| Decision Efficiency | `kpis.decision_efficiency` | Completion rate + ARM analysis quality |
| AI Productivity Boost | `kpis.ai_productivity_boost` | ARM usage + code-quality trend |
| Focus Quality | `kpis.focus_quality` | Watcher sessions: duration, distractions |
| MasterPlan Progress | `kpis.masterplan_progress` | % tasks done + ahead/behind schedule |

Optionally show each KPI's weight from `scores/me` → `weights{}` so the user sees what drives the
master number.

### Row B — 3 axes
Source: `GET /apps/analytics/three-axis`. **Keep units honest — never fake-combine $ and declared
units** (the backend deliberately keeps them separate).

| Tile | Fields | Shows |
|---|---|---|
| Volume | `volume.effort_hours`, `volume.completed_count` | Effort-weighted work, last 14 days |
| Trajectory | `trajectory.mean_pace_ratio`, `.ahead` / `.on_time` / `.behind` | Est-vs-actual pace + the split |
| Worth | `worth.realized_revenue` **($, real)** + `worth.declared_total` (units) | Two separate figures |

### Empty state (the anti-pattern to avoid)
If after a recalculate `master_score === 0` and `kpis` is empty, render an explicit message —
"Not enough activity yet; complete a few tasks to build your score." A blank panel here would be
the exact response-shape-blindness bug class the whole walk kept hitting.

### Deliberately excluded
No social/engagement tiles on this surface — it's manual-ingest-only and would misrepresent as
live. If wanted later, it belongs in a clearly-labeled "LinkedIn — last import `{date}`" card,
never a real-time tile.

---

## API inventory

| Endpoint | Backend | Client fn (`client/src/api/analytics.js`) |
|---|---|---|
| `GET /apps/analytics/scores/me` | ✅ live (`score_get_node`) — **auto-computes on first miss** | ✅ `getMyScore` |
| `GET /apps/analytics/scores/history` | ✅ live (`score_history_node`) | ✅ `getScoreHistory` |
| `POST /apps/analytics/scores/recalculate` | ✅ live | ✅ `recalculateScore` |
| `GET /apps/analytics/three-axis` | ✅ live (`get_three_axis_snapshot`) | ❌ **add `getThreeAxis`** |

**Route-constant note:** score constants come from ui-kit's `ROUTES.ANALYTICS` and receive the
`/apps` mount via `client/src/api/_routes.js` (so `SCORES_ME` → `/apps/analytics/scores/me`).
`three-axis` has **no ui-kit constant** — add it either as a literal path in `analytics.js`
(`/apps/analytics/three-axis`) or extend the route map. The `/compute` prefix in `_routes.js`
applies only to the `CALCULATE_*` keys, so it does not interfere.

---

## Implementation steps — all ✅ done (2026-07-31)

1. ✅ **`getThreeAxis`** added to `client/src/api/analytics.js` (literal `/apps/analytics/three-axis`
   path — no ui-kit constant).
2. ✅ **`KPIDashboard` rewritten** (`client/src/components/shared/KPIDashboard.jsx`) — Hero ring +
   provenance + Recalculate + history sparkline, Row A (5 KPIs), Row B (3 axes), real empty state.
   Replaced in place, so the `App.jsx:245` route needed no change. Verified live: Row B renders
   with correct numbers.
3. ✅ **Manual Tools drawer** — new `/tools` page (`ManualTools.jsx`) under the ANALYTICS nav group
   holds the 10 parked what-if calculators + `TwrPanel` (TWR, extracted from the old console),
   behind an honesty banner. `AppShell.jsx` + `App.jsx` wired.
4. ✅ **Colliders deleted** — `ExecutionSpeedPanel`, `DecisionEfficiencyPanel`,
   `AIProductivityBoostPanel` removed (real system-fed twins live on `/kpi`).
5. ✅ **Item 32 resolved via option B** — `ExecutionConsole.jsx` rewritten into a *real* execution
   console: live request pulse (`observability/requests`), filterable flow-runs table
   (`flows/runs`), per-run execution-graph trace (`observability/execution_graph/{trace_id}`).
   The `/executions` route/nav are unchanged, so coupled tests stay green. Full suite: 171 pass.

---

## Manual calculators — disposition (split, don't blanket-delete)

> **Decision (owner, 2026-07-30): park not delete.** Group 2 goes behind a labeled drawer,
> not into the trash; group 1 (name-colliders) is the only outright deletion.

**Delete outright — the 3 name-colliders.** `ExecutionSpeedPanel`, `DecisionEfficiencyPanel`,
`AIProductivityBoostPanel` share exact names with real system-fed KPIs but compute from invented
inputs. Two "Decision Efficiency" numbers that disagree is a guaranteed-confusion trap; collision
harm outweighs option value.

**Park behind a "Manual tools" drawer — the what-if calculators.** RevenueScaling, BusinessGrowth,
MonetizationEfficiency, AttentionValue, IncomeEfficiency, LostPotential, Engagement, Impact,
AIEfficiency, EngagementRate. These have a legitimately different use (planning / what-if math),
and ephemeral inputs are correct for that. Move them off `/kpi` into a labeled drawer:
*"Manual calculators — scratch-pad math, not connected to your data."* Reversible and cheap; delete
in a later pass once the drawer proves unused.

**Why park over delete (group 2):** deletion is the irreversible move, and there's no usage data
yet showing nobody uses them as planners. Parking removes them from the dashboard surface (the
actual problem) without destroying working code. Group 1 is the exception because the name
collision is actively harmful.

This disposition also resolves **item 32**: the 7 platform-stranded panels are all group-2
calculators; moving them into the app-side drawer un-strands them and empties the misnamed
Executions tab in one stroke.

---

## Risk & notes

- **Low risk.** Every endpoint is already live and walked; no backend, no migrations, no runtime
  changes. The failure surface is client rendering only.
- **Self-seeding is a feature.** `score_get_node` calls the Infinity orchestrator on first miss,
  so a brand-new user hitting `/kpi` gets a score computed on the spot — no empty-state dead-end
  (but still handle the genuinely-zero-activity case per Empty State above).
- **Honesty over completeness.** Show `confidence` and `data_points_used` prominently. A low-data
  score should look provisional, not authoritative.

---

## Open questions for the owner

1. **`/analytics` (item 18's other half):** LinkedIn-specific and owner-specific — still slated for
   removal rather than redesign? This plan doesn't touch it.
2. ~~**Group-2 calculators:** park behind a drawer or delete now?~~ **Resolved 2026-07-30: park.**
3. **Weights display:** show per-KPI weights on the tiles, or keep the master number clean?
