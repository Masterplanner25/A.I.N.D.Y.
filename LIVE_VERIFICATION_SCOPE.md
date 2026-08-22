# Live Verification Scope

## Purpose

This document defines the scope of the live stack verification phase. Work happens
in `aindy-apps-monolith`, but the primary objective is confirming that
**`aindy-runtime` works correctly end-to-end** — by activating it with the 16 domain
apps it was designed to serve, from a real user's perspective.

> **Status (2026-07-22): live verification is COMPLETE.** Both halves have been walked
> — the Product UI and the Platform/operator UI — and the Phase 2b cross-cutting checks
> have been run. **Phase 2c is gated on real usage, not on outstanding work** (see 2c).
> 34 findings are recorded in `docs/handoffs/FRONTEND_WALK_LOG.md`; ~25 defects were
> fixed and merged across PRs #131–#166. What remains from this phase is a *decision
> list*, not a bug list — the largest cluster being walk-log items 18 / 29 / 32, which
> are one decision seen from three surfaces.
>
> **Historical note (product-UI half):** completed first, 23 findings and ~19 fixes
> across PRs #131–#154. The platform half followed in #158–#165.

> **Update (2026-08-22) — the phase verdict stands; two of its load-bearing claims do not.**
>
> **The decision list is closed.** Walk-log items 18 / 29 / 32 — called "the largest cluster"
> above — all closed 2026-07-31 via PRs #168–#171. What remains of item 18 is its other half:
> `/analytics` is still owner-specific, and the owner leaned toward removal.
>
> **2c was blocked on the wrong thing.** The numbers below (`three_axis_shadow_records` = 2,
> `infinity_expectation_predictions` = 1, "~20+ days to reach the fitting floor") are stale: the
> live counts are **58** and **320**, and the floor was crossed long ago.
> `docs/handoffs/SOAK_AUDIT_2026-08-15.md` then measured 294 / 269 / 285 and concluded the
> opposite of what this section assumes — **"the gate that could never open."** Not for want of
> rows, but because they are the same measurement repeated. **The blocker is variety, not volume,
> and not time.** The reasoning below about synthetic traffic was right; what it missed is that
> real traffic from one account has the same defect. Tracked as `SOAK-THEN-FLIP-1` in
> `TECH_DEBT.md`.
>
> **The soak ledger was then reset and nothing said so.** 294 records across 25 users on
> 2026-08-15; **58 across 4 users** now — consistent with the account purge to 4 accounts on
> 2026-08-16. (`infinity_expectation_predictions` was spared: it keys off `loop_adjustment_id`,
> not `user_id`, which is why it grew while three-axis fell.) 2c calls "surface the soak readout"
> *optional, not required* — and that judgement is what made an 80% loss invisible. It should now
> be read as required.
>
> **The ownership question this phase never asked.** Its stated purpose is proving the *runtime*,
> yet it produced ~25 app-side fixes. An audit on 2026-08-22 tagged all 34 findings by owner:
> **24 app, 6 runtime, 2 both, 1 undecided, 1 environment** — and of the 8 with runtime ownership,
> only one (item 6) became a feature request at the time. The dominant class of the whole phase,
> response-shape mismatch, was fixed **eleven times in client code and raised with the runtime
> zero times**. Three requests were filed retroactively: **FR-19** (envelope contract), **FR-20**
> (the guard replacing a raised 4xx with a 500), **FR-21** (5,949 lines of operator surface built
> app-side next to a runtime-owned one — offered back, with our copy retired on adoption).
>
> **The process fix:** the walk log's finding format now carries a required **Owner** field
> (`app` / `runtime` / `both` / `undecided` / `env`). Findings arrive wearing app clothes because
> the walk is driven from the UI, and the cheapest fix is always the one in front of you. Asking
> ownership per finding is the step that was missing — not a rule anyone broke.

Integration tests proved API contracts. This phase proves the runtime behaves correctly
when a human navigates the product, not when a test harness calls an endpoint.

Development work on the apps themselves is expected and in scope — the apps are the
real-world surface that exposes runtime behaviour. A bug found in the UI may be a
route bug, a flow bug, a syscall bug, or a runtime pipeline bug. All are in play.

---

## Stack

| Component | Repo | Role |
|---|---|---|
| Runtime API | `aindy-runtime` | FastAPI server, syscall dispatcher, flow engine, scheduler |
| 16 domain apps | `aindy-apps-monolith` | Routes, flows, models, bootstrap |
| Product UI | `aindy-apps-monolith/client/` | React SPA — the product surface |
| Platform UI | **both — unresolved** | `aindy-runtime` serves one at `/platform/`; this repo also builds `client/platform.html`. See the 2026-08-22 status entry and FR-21. |
| Postgres | docker-compose | Persistent state |
| Redis | docker-compose | Pub/sub, rate limiter |
| MongoDB | docker-compose | Memory/search backend |

Boot command (from `aindy-apps-monolith` root):

```bash
AINDY_APP_PLUGIN_MANIFEST=./aindy_plugins.json aindy-runtime serve
```

Expected on boot: `boot_profile=default-apps`, `app_plugins_loaded=True`,
`app_plugin_count=16`, all 3 core domains registered (`tasks`, `identity`, `analytics`).

Verified live 2026-07-22 (when `bridge` still existed, so the count read 17):
`boot_profile=default-apps`, `boot_mode=app-profile`,
`app_plugins_loaded=true`, `app_plugin_count=17`, `deployment_profile=single-instance`,
`background_leadership_mode=in-process`.

> Doc-drift corrected on 2026-07-22: this file previously said 16 apps and named
> `agent` as a core domain. `grep IS_CORE_DOMAIN apps/*/bootstrap.py` shows the three
> `True` values are **`tasks`, `identity`, `analytics`** — `agent` is a degradable
> peripheral. (`CLAUDE.md` names only two and is corrected in the same change.)

---

## Verification surfaces

### Product UI — `client/`

The primary surface. Verify each domain panel loads, displays real data, and
handles errors/empty states correctly.

| Domain | Entry point | Key things to verify |
|---|---|---|
| Auth | `/login`, `/register` | Register, login, token refresh, logout |
| Identity | `IdentityDashboard` | Profile loads, preferences save, evolution log updates |
| Tasks | `TaskDashboard` | Create, list, start, pause, complete; status updates visible |
| ARM | `ARMAnalyze`, `ARMGenerate`, `ARMLogs`, `ARMConfig`, `ARMMetrics`, `ARMConfigSuggest` | Full ARM workflow; config persists per user; logs appear; metrics reflect sessions |
| Analytics | `AnalyticsPanel`, KPI weights, policy thresholds | Calculations return data; panels display scores |
| Agent | `AgentConsole` | Create run, approve, view steps/events; tools list loads |
| Freelance | `FreelanceDashboard` | Orders, payments, refunds visible |
| MasterPlan | `MasterPlanDashboard` | Plans load; task graph renders |
| Memory | `MemoryBrowser` | Nodes browsable; search returns results |
| Search | `ResearchEngine`, `SearchHistory` | Queries run; history persists |
| Social / Feed | `Feed`, `PostComposer`, `InfiniteNetwork` | Feed loads; posts compose |

### Platform UI — `/platform`

The operator surface. Verify platform-layer features work against live traffic
generated by the product UI.

| Panel | Key things to verify |
|---|---|
| Flows | Flow runs appear after product actions that trigger flows |
| Agent Registry | Registered agents visible; approval inbox works |
| Observability | Metrics update; trace IDs from product requests appear |
| Strategies | Strategy list loads; config readable |
| Automation | Automation logs populate as product events fire |
| Health | All domains healthy; syscall registry count correct |

---

## What counts as "working"

- No silent 500s — errors surface as structured responses, not blank panels
- Data isolation — user A cannot see user B's records
- State persistence — actions taken in the UI survive a page refresh
- Flow feedback — operations that run flows (task start, ARM analyze, agent runs)
  return results that the UI actually renders, not raw JSON blobs
- Trace continuity — X-Trace-ID in responses is observable (dev tools) and matches
  platform observability records

---

---

## Phase 2 — what remains (defined 2026-07-22)

The product-UI table above is done. Three bodies of work remain, in dependency order.

### 2a. Platform UI — the operator surface — ✅ WALKED 2026-07-22

All eight panels reached and exercised. Seven defects found, six fixed:
the dev proxy swallowing every `/platform` API call (#158), the Registry key mismatch
plus per-panel error boundaries (#159), the Strategies null-score crash (#161), the
**complete absence of navigation** — 7 of 8 panels were reachable only by typing a URL
(#163) — and the Agent Console envelope crash (#164). Two findings logged unfixed:
client error telemetry has never worked (item 28) and the Executions tab is 13
app-domain calculators on the operator surface (item 32). One design finding: the
operator UI is a record, not a control plane — 24 write routes exist, 5 are wired
(item 29).

#### Original definition


`client/platform.html` is a second Vite entry point; the panels live in
`client/src/components/platform/` (`FlowEngineConsole`, `AgentRegistry`,
`AgentApprovalInbox`, `ObservabilityDashboard`, `HealthDashboard`, `ExecutionConsole`,
`RippleTraceViewer`). The API exposes **51 `/platform/*` routes**.

This is the half that actually verifies the *runtime* rather than the apps: flow runs,
the syscall registry, the scheduler, dead-letter queues, execution graphs, node
registration and Nodus scripts are all runtime-owned surfaces.

It is walked **after** the product UI on purpose — the panels only show something if
live traffic exists, and the product walk has now generated it.

### 2b. Cross-cutting checks — ✅ RUN 2026-07-22

| Check | Result |
|---|---|
| Data isolation | **PASS** — two fresh users, one task each: neither sees the other's. Memory nodes fully separated (6 vs 6, **0 shared ids**), scores per user. |
| Trace continuity | **PASS** — `X-Trace-ID` matches `data.trace_id` and resolves to a 12-node `execution_graph`. Caveat logged as walk-log item 33: the envelope's own `trace_id` is a *different* id resolving to a 2-node graph, so debugging from the response body misleads. |
| State persistence | **PASS** — exercised continuously through both halves of the walk; every fixed surface was re-verified after reload. |
| Dead-letter | **Read path PASS, capture path unexercised.** Forced a real failure (`POST /platform/flows/task_create/run` with invalid state → 500). The failed run is recorded and visible via `/platform/flows/runs?status=failed`, but both DLQ surfaces stayed at count 0 — **correctly**: dead-lettering is `flow_run.dead_lettered_at`, set by the resume watchdog for *stranded* runs past `STUCK_RUN_THRESHOLD_MINUTES`, not by an ordinary synchronous failure. Proving capture needs a genuinely stuck run and real elapsed time. |
| Scheduler liveness | **PASS with a gap.** `scheduler_running: true`, `is_leader: true`, and a lease heartbeat that is current and advancing — itself proof the 60s heartbeat job runs. But the status payload exposes **no job inventory** (walk-log item 34), so the five registered jobs cannot be confirmed from the operator surface. |

**One false alarm worth recording:** an early probe reported `/apps/analytics/scores/me` → 404 for
every user. The route is `/apps/scores/me` — the probe used the wrong path. Verified working:
`master_score: 42.21` with a populated KPI block and history. No defect.

#### Original definition

### 2b. Cross-cutting checks

These cut across every panel and are cheapest to verify once, deliberately:

| Check | How |
|---|---|
| Trace continuity | Take an `X-Trace-ID` from a product request, find it in `/platform/observability/execution_graph/{trace_id}` |
| Data isolation | Two users, same surface — confirm no record bleed (the walk created many throwaway accounts; use two) |
| State persistence | Every product action survives a refresh (spot-checked during the walk, never done systematically) |
| Dead-letter behaviour | Force a flow failure, confirm it lands in `/platform/observability/dead-letter` and can be drained |
| Scheduler liveness | `/platform/observability/scheduler/status` reflects the registered jobs (task reminders 1m, recurrence 6h, lease heartbeat 60s, wait-recovery 60s, resume watchdog) |

### 2c. Flag soaks — ⏸ GATED ON REAL USAGE (not on work)

**Status as of 2026-07-22: the shadow flags are ON and recording. There is no
outstanding task here.** 2c is not a backlog item waiting to be picked up — it is a
consequence of the product being used. It completes when real usage produces real
data, and that is downstream of the redesign.

**What is already running, verified live:**

- `AINDY_INFINITY_THREE_AXIS_SHADOW=1` and `AINDY_INFINITY_LEARNED_SHADOW=1` reach the
  process (they did not before — see #156; they were set in `.env` but never declared
  in the compose `environment:` block, so no shadow data was ever collected).
- `three_axis_shadow_records` fills on every score event. Volume is real signal since
  #157 wired `estimated_hours` into the task form — before that `effort_hours` was
  always 0 and `volume_score` with it.
- `infinity_expectation_predictions` fills when a `LoopAdjustment` matures.
- A cron job — **`Daily Infinity score recalculation`, `hour=7`** — walks every user,
  runs the orchestrator, then (gated on the learned-shadow flag) calls `train()` and
  `evaluate()` and logs the comparison:
  `[Infinity Scheduler] Expectation shadow: trained=… overall=…`

> **SUPERSEDED 2026-08-22 — do not act on the numbers in this paragraph.** The floor was crossed;
> live counts are 58 and 320. `SOAK_AUDIT_2026-08-15` found the gate cannot open on volume at all
> ("the same measurement repeated"), and the ledger was later reset by the account purge. See the
> status entry at the top and `SOAK-THEN-FLIP-1` in `TECH_DEBT.md`. Retained below because the
> reasoning about synthetic traffic is still correct and still worth reading.

**The blocking number:** `MIN_TRAIN_SAMPLES = 20` per `decision_type`. Below it `train()`
abstains with `insufficient samples`. Current rows: `three_axis_shadow_records` = 2,
`infinity_expectation_predictions` = 1. At roughly one matured decision per active user
per day, a single account needs **~20+ days of genuine daily use** just to reach the
fitting floor — and reaching it is not the same as having evidence worth flipping on.

**Why synthetic traffic is deliberately not being used.** Seeding a few dozen
task create/complete cycles would cross the floor in minutes, and it would validate the
*plumbing* — ledger fills, axes compute, `train()` fits, `evaluate()` reports an MAE.
It would **not** validate the decision. The learned calibrator exists to answer "does a
model fit on *this user's* behaviour beat the heuristic?"; fit it on synthetic churn and
the MAE comparison is meaningless while looking exactly like validation. Flipping
`AINDY_INFINITY_LEARNED_ADVISORY` on that evidence would be worse than not flipping it.

The same applies to three-axis Phase D: `worth_score` reads `declared_total` /
`realized_revenue` from freelance and masterplan, and Trajectory needs a *series* of
completions — synthetic data would fill both with fiction.

**So the sequence recorded below still stands, but step 2 ("generate real traffic") is
gated on the product being usable enough to dogfood.** That is the redesign, which is
the actual critical path. Everything downstream of the soak — three-axis Phase D,
learned-recursion Phase 2, the durable-execution flip — inherits that gate.

**Two optional pieces of work, neither required:**

1. *Seed for plumbing validation only* — cross the floor synthetically, confirm
   `train()`/`evaluate()` run end-to-end, and explicitly do **not** treat the output as
   flip evidence. Worth it only to find a broken soak now rather than in three weeks.
2. *Surface the readout* — today the only way to see soak progress is grepping the API
   logs once a day. A row count plus last-evaluate summary on an operator surface would
   make "is the soak progressing?" answerable at a glance. Pairs naturally with the
   scheduler job-inventory gap (walk-log item 34).

---

#### Original definition (flag inventory at the time of writing)

**Verified in the running container: every one of these was unset, i.e. default-off.**
No shadow data existed for any of them, which is why the "soak then flip" work had
stayed parked. The two shadow flags have since been turned on (#156).

| Flag | Purpose | State |
|---|---|---|
| `AINDY_INFINITY_THREE_AXIS_SHADOW` | Volume/Worth/Trajectory computed and recorded, no behaviour change | unset |
| `AINDY_INFINITY_THREE_AXIS_ADVISORY` | Blend the three-axis score advisorily | unset |
| `AINDY_INFINITY_WORTH_WEIGHT` / `_TRAJECTORY_WEIGHT` | Blend weights | unset |
| `AINDY_INFINITY_LEARNED_SHADOW` | Learned REFLECT calibrator, shadow | unset |
| `AINDY_INFINITY_LEARNED_ADVISORY` | Learned calibrator, advisory | unset |
| `AINDY_REASONING_NODUS_NATIVE` | nodus_vm as the reasoning path | unset |
| `AINDY_NEXT_ACTION_ACTING` | Next-action pre-dispatch | unset |
| `AINDY_SEARCH_EMBEDDING_RANKING` / `_OUTCOME_WEIGHTING` / `_OUTREACH_SEND` | Search ranking + real outreach | unset |
| `AINDY_DURABLE_CONTINUATION` / `_ALL` / `_FOLD_REPAIR` / `_STEP_GRANULARITY` | Durable execution | all `False` |

**The soak is a sequence, not a switch:**

1. Turn the **shadow** flags on (they are shadow *because* they change nothing observable).
2. Generate real traffic — the same product paths the walk exercised.
3. Read the recorded shadow data and compare it against live behaviour.
4. Only then flip **advisory**, and re-soak.
5. Flip to acting/default only after advisory has a clean window.

Steps 1–2 are safe and unblock everything else; the flip decisions at 4–5 are the
actual gated calls. `AINDY_SEARCH_OUTREACH_SEND` is the one exception — it sends real
outreach and must never be part of a soak batch.

### Open questions for Phase 2

- `AINDY_AGENT_PLANNER_BACKEND=anthropic_chat` while `AINDY_AGENT_PLANNER_MODEL=gpt-4o`
  and `AINDY_CLAUDE_PLANNER_MODEL` is empty. The OpenAI model setting only feeds the
  `openai_chat_completion` helper the runtime hands to backends, so this is probably
  benign — but which model the Anthropic planner actually resolves to needs confirming
  live, not by reading defaults.

---

## Known gaps to watch for

- Any panel that shows a blank/empty state when data should exist — likely a
  response shape mismatch between the route's envelope and the UI's data extractor
- Any action that returns 200 but the UI doesn't update — likely the UI is reading
  the wrong key in `body.data`
- ARM config changes not persisting across users — per-user scoping (`arm_config.id`
  keyed by UUID) was fixed; verify it holds in the live UI
- Agent runs stuck in `pending_approval` with no inbox entry — approval inbox
  and run state machine must be in sync

**Retrospective (2026-07-22): the first two gaps above were the dominant failure mode
of the entire product walk.** "Blank panel where data should exist, caused by an
envelope/extractor mismatch" was confirmed **four separate times** — social (#150),
tasks (#151), ARM's blank failure render (#152) and identity (#154) — plus the earlier
dashboard overview (#137). A related third form appeared repeatedly: a route returning
**HTTP 200 with `status: "success"` while the payload carried the real error**, so the
UI rendered nothing and reported nothing (social degrade #149, ARM analyze #152).

Carry both into the Platform UI walk as the *primary* hypothesis when a panel looks
empty. Three distinct response conventions exist across the API and must each be
handled: enveloped `{status, data}`, enveloped with the collection under a named key
(`data.tasks`), and unenveloped (`/apps/memory`, `/apps/masterplans/`). See walk-log
item 13.
