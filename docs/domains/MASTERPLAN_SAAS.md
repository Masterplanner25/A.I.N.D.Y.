---
title: "Masterplan SaaS - Canonical Definition & Evolution Plan"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Masterplan SaaS - Canonical Definition & Evolution Plan

---

## 1. System Definition (Canonical)

The Masterplan SaaS layer is A.I.N.D.Y.'s execution-strategy surface. It is not a
general automation SaaS. It is a **Masterplan trajectory engine** that:

- captures a strategic plan (Genesis -> MasterPlan)
- enforces lifecycle (draft -> lock -> activate)
- measures execution as time-compression against a declared target state
- prioritizes dependency resolution to compress downstream timelines

---

## 2. Core Lifecycle (Canonical Pipeline)

```text
Genesis -> MasterPlan -> Lock -> Activate -> Execute -> Measure -> Reproject
```

---

## 3. Core Components

### 3.1 Genesis (Plan Formation)

**Implementation:**
- `apps/masterplan/routes/genesis_router.py`
- `apps/masterplan/services/genesis_ai.py`
- `apps/masterplan/services/masterplan_factory.py`

**Current Capabilities:**
- guided strategic draft
- synthesis + audit
- lock into MasterPlan

---

### 3.2 MasterPlan Artifact

**Implementation:**
- `apps/masterplan/routes/masterplan_router.py`
- `apps/masterplan/models.py`

**Current Capabilities:**
- versioned plan records
- posture classification
- activation state

---

### 3.3 Execution Tracking

**Implementation:**
- `apps/tasks/routes/task_router.py`
- `apps/tasks/services/task_service.py`
- `apps/analytics/routes/analytics_router.py`

**Current Capabilities:**
- task tracking
- analytics ingestion
- basic dashboard overview

---

## 4. Current Implementation (Reality)

**Implemented:**
- Genesis session lifecycle (create -> message -> synthesize -> audit -> lock)
- MasterPlan creation and activation
- MasterPlan anchor fields and update endpoint
- ETA projection endpoint and dashboard panel
- Task CRUD + analytics ingestion
- dependency persistence and DAG-based blocking/unlock behavior
- MasterPlan-linked task generation and automation dispatch
- basic dashboards

**Missing or Drifted vs Masterplan Module docs:**
- ETA projection is now plan-scoped, cascade/critical-path aware, and
  continuous-time (2026-06-30): tasks carry an optional `estimated_hours` effort
  estimate and the projection runs on remaining *effort* + the effort-weighted
  critical path when estimates exist (`projection_basis="duration"`), falling
  back to count-based cascade otherwise
- external automation connectors now reach social/CRM/payment surfaces (2026-06-30);
  what remains is runtime-owned hardening (a first-class connector registration hook
  + capability-enforced outbound I/O), not app wiring

---

## 5. Doc -> Code Parity Table

| Documented Capability | Evidence in Docs | Implementation Reality | Status | Primary Files |
| --- | --- | --- | --- | --- |
| Genesis -> MasterPlan lifecycle | Masterplan Genesis Module | Implemented | Implemented | `apps/masterplan/routes/genesis_router.py`, `apps/masterplan/services/masterplan_factory.py` |
| MasterPlan activation | Genesis Module | Implemented | Implemented | `apps/masterplan/routes/masterplan_router.py`, `client/src/components/app/MasterPlanDashboard.jsx` |
| Masterplan anchor / target state | Masterplan Plans doc | Anchor fields, endpoint, and UI are implemented | Implemented | `apps/masterplan/models.py`, `apps/masterplan/routes/masterplan_router.py`, `client/src/components/app/MasterPlanDashboard.jsx` |
| ETA projection / timeline compression | Masterplan Plans doc | Plan-scoped, cascade/critical-path-aware, and continuous-time: with per-task effort estimates it projects on remaining effort + the effort-weighted critical path (`projection_basis="duration"`), reducing to count-based cascade when estimates are absent | Implemented (duration-aware) | `apps/masterplan/services/eta_service.py`, `apps/tasks/services/task_service.py`, `client/src/components/app/MasterPlanDashboard.jsx` |
| Dependency cascade model | Masterplan Plans doc | Dependency metadata, DAG construction, blocked-task enforcement, and downstream unlock behavior exist | Implemented | `apps/tasks/models.py`, `apps/tasks/services/task_service.py` |
| Execution automation layer | Masterplan SaaS docs | MasterPlan generates tasks and dispatches bound automation through the execution layer; connectors reach external social/CRM/email/webhook/payment surfaces (app builds the call, wrapped in the runtime `perform_external_call` boundary) | Implemented | `apps/masterplan/services/masterplan_execution_service.py`, `apps/automation/services/automation_execution_service.py` |
| Execution analytics dashboard | SaaS docs | The MasterPlan surface now shows plan-scoped cascade execution metrics directly (basis, critical-chain depth, ready/blocked); a dedicated cross-plan execution/compression dashboard is still not built | Partial | `apps/analytics/routes/analytics_router.py`, `apps/dashboard/routes/dashboard_router.py`, `client/src/components/app/MasterPlanDashboard.jsx` |

---

## 6. Gap -> File Mapping

| Gap | Impact | Files to Update |
| --- | --- | --- |
| ETA projection is flat velocity-based only — RESOLVED (2026-06-30): now plan-scoped, cascade/critical-path aware, and continuous-time (per-task `estimated_hours` → remaining-effort + effort-weighted critical path, `projection_basis="duration"`) | Compression reflects dependency depth *and* heterogeneous task sizes, not just raw counts | `apps/masterplan/services/eta_service.py`, `apps/tasks/services/task_service.py` |
| External automation connectors — RESOLVED (2026-06-30): social + CRM now reach external surfaces alongside email/webhook/stripe. Remaining is runtime-owned: a first-class connector registration hook + capability-enforced outbound I/O | Execution SaaS promise (external delivery) now met; hardening is runtime work | `apps/automation/services/automation_execution_service.py` |

---

## 7. Risk Register

| Risk | Type | Failure Mode | Impact | Likely? |
| --- | --- | --- | --- | --- |
| Masterplan drift | Product | Plans exist without dependency-aware trajectory signal | Core value missing | High |
| Docs vs runtime mismatch | Product | SaaS docs understate implemented anchor/ETA features and overstate execution depth | Expectation gap | High |
| Projection still under-models dependency cascade | Technical | Resolved (2026-06-30): ETA is plan-scoped, uses critical-path depth as a sequential floor, and is continuous-time (effort-weighted critical path from per-task `estimated_hours`) | Weak projection quality | Low |
| External automation connectors are partial | Business | Mitigated (2026-06-30): social/CRM/email/webhook/payment all reach external surfaces; residual is runtime-owned hardening (connector registration hook + capability-enforced outbound I/O), not delivery capability | Revenue risk | Low |

---

## 8. System Classification

The Masterplan SaaS layer is currently:

> A strategic planning + activation system with dependency-aware, continuous-time
> task execution and automation binding that reaches external social/CRM/email/
> webhook/payment surfaces. Remaining refinements are runtime-owned (a first-class
> connector registration hook + capability-enforced outbound I/O).

---

## 9. Evolution Plan (System Roadmap)

### Phase v1 - Persist Dependency Structure
**Goal:** make execution order real  
**Actions:**
- persist task dependencies in the task model ✅
- carry dependencies through task creation and retrieval ✅

### Phase v2 - Timeline Compression Output
**Goal:** make TWR actionable  
**Actions:**
- compute dependency-aware ETA shift per task batch
- return updated projection from execution endpoints

### Phase v3 - Dependency Awareness
**Goal:** encode upstream constraint removal  
**Actions:**
- add dependency-aware task ordering ✅
- include cascade impact in projection and execution feedback

### Phase v4 - Automation Surface
**Goal:** convert planning into execution  
**Actions:**
- add automation integration layer (social, CRM, payments) — partial

---

## 10. Next Steps

### Step 1 - Deepen cascade impact in projection - DONE
**Files:** `apps/masterplan/services/eta_service.py` (+ `apps/analytics/services/scoring/infinity_service.py` consumes the output)  
**Outcome:** ETA is now **plan-scoped** (fixed a bug where it counted tasks
user-wide) and **cascade-aware**. `calculate_eta` pulls the dependency graph via
the existing `sys.v1.tasks.get_graph_context` syscall, scopes to the plan's tasks
by `masterplan_id`, and projects with `_project_days` = `max(remaining/velocity,
critical_depth / min(velocity, 1.0))` — so the longest remaining dependency chain
imposes a sequential floor that flat throughput can't beat. Completing a blocking
task shortens that chain (`critical_depth`) and shifts the projection earlier. The
result now also surfaces `critical_depth`, `blocked_tasks`, `ready_tasks`, and
`projection_basis` (`cascade` | `velocity` | `insufficient_data`). It degrades
gracefully to the legacy flat-velocity estimate when the graph is unavailable.
The infinity `masterplan_progress` KPI (which reads `plan.days_ahead_behind`)
improves for free — no change needed there.

**Tests:** `tests/unit/test_masterplan_eta_cascade.py` — cascade math, plan
scoping + critical-depth derivation, the integration path (cascade vs velocity
fallback), and missing-plan handling.

### Step 2 - Expose MasterPlan execution metrics directly - DONE
**Files:** `client/src/components/app/MasterPlanDashboard.jsx`,
`client/src/components/app/TaskDashboard.jsx`,
`client/src/context/MasterplanProjectionContext.jsx`, `client/src/App.jsx`  
**Outcome:** the active plan's ETA panel now surfaces the Step-1 cascade metrics
directly on the MasterPlan surface rather than relying on generic dashboard views.
The projection endpoint (`get_masterplan_projection` → `calculate_eta`
pass-through) already returns the cascade fields, so surfacing them is purely the
consuming UI: the `ETAProjectionPanel` renders a **`cascade`** basis chip when the
projection is dependency-aware, a **critical-chain depth** line (`{critical_depth}
deep`, shown only when the chain is longer than one), and a **`{ready} ready ·
{blocked} blocked`** line — alongside the existing velocity / ahead-behind
metrics. It degrades cleanly on the velocity fallback (no chip, no critical-chain
line).

The panel also consumes the **Step-3 completion-response projection reactively**.
Task completion returns the recomputed cascade projection under
`orchestration.masterplan_projection`, but the task surface and MasterPlan surface
are separate lazily-loaded routes that never mount together, so that projection
was previously discarded until the panel refetched on its own. A small
`MasterplanProjectionProvider` context (mounted above the app shell, so it
survives navigation between `/tasks` and `/masterplan`) now carries it: the task
surface publishes the projection on completion, and the ETA panel adopts it — a
pushed projection takes precedence over the panel's own fetched baseline, with no
refetch.

**Tests:** `client/src/test/masterplan-dashboard.test.jsx` — cascade metrics
render on the active plan, and the chip + critical-chain line are omitted on the
velocity fallback. `client/src/test/masterplan-projection-reactive.test.jsx` —
completing a task reactively updates the MasterPlan panel to the fresh cascade
projection (no second projection fetch), and leaves it untouched when completion
carries no reprojection.

### Step 3 - Return MasterPlan reprojection from task completion flows - DONE
**Files:** `apps/tasks/services/task_service.py`  
**Outcome:** task completion now returns the refreshed MasterPlan projection.
`orchestrate_task_completion` already recomputed the active plan's ETA but
discarded it; it now captures the (cascade-aware, Step 1) projection via the
extracted `_recalculate_active_masterplan_eta` helper and includes
`masterplan_id` + `masterplan_projection` in its result. That result already
propagates to the `/tasks/complete` response under `task_orchestration` (the
`task_orchestrate` flow node merges the syscall data via `output_patch`, and
`_flow_envelope` returns the full flow data), so **no flow/route changes were
needed** — completing a task surfaces fresh projection data (velocity, ETA,
days ahead/behind, critical_depth, projection_basis) for the MasterPlan surface
to consume.

**Tests:** `tests/unit/test_task_completion_reprojection.py` — the capture helper
(active plan / no plan / no anchor / failure) and the orchestration return
contract carrying the projection keys.

### Step 5 - Continuous-time (per-task-duration) compression - DONE
**Files:** `apps/tasks/services/task_service.py`, `apps/tasks/schemas/task_schemas.py`,
`apps/tasks/routes/task_router.py`, `apps/tasks/syscalls/syscall_handlers.py`,
`apps/masterplan/services/eta_service.py`, `client/src/components/app/MasterPlanDashboard.jsx`  
**Outcome:** the ETA model was count-based — every task weighed the same. Tasks
now carry an optional effort estimate (`estimated_hours` on create → `Task.duration`,
hours), and the projection upgrades to **continuous time** when estimates exist.
`build_task_graph` exposes per-node `duration` and a `critical_duration` map (the
effort-weighted longest *remaining* dependency chain; completed nodes contribute
0). `calculate_eta` scales task/day velocity by average task size into hours/day,
then projects on **remaining effort** and the **effort-weighted critical path**:
`max(remaining_effort / work_velocity, critical_path_effort /
min(work_velocity, 8h/day))` — the 8h/day cap being the single-stream sequential
floor. This reduces *exactly* to the count-based cascade estimate when tasks are
uniform, so a plan with a few large tasks now projects longer than its task count
implies. Basis becomes `projection_basis="duration"`; the result also surfaces
`remaining_effort`, `critical_path_effort`, and `work_velocity`. It degrades to
count-based cascade when no estimates exist, and to flat velocity when the graph
is unavailable. The dashboard shows a `duration` chip and an "Effort left: ~Xh"
line.

**Tests:** `tests/unit/test_masterplan_eta_duration.py` (effort math, effort scope
metrics, duration-basis integration, cascade fallback),
`tests/unit/test_task_graph_duration.py` (duration-weighted critical path,
completed-effort exclusion, `estimated_hours` persistence), and
`client/src/test/masterplan-dashboard.test.jsx` (duration chip + effort line).

### Step 4 - Extend external automation connectors - DONE
**Files:** `apps/automation/services/automation_execution_service.py`  
**Outcome:** the MasterPlan-linked automation layer now reaches external
social/CRM/payment surfaces. Payment (`stripe`/`subscription`) and `email`/
`webhook` were already external; the two gaps — **CRM** (a pure echo stub) and
**social** (internal Mongo feed only) — are now wired, mirroring the existing
pattern: the app builds the outbound HTTP request and wraps it in the runtime's
`perform_external_call` observability boundary (no runtime change or new
connector hook needed — outbound I/O is app-owned).
- **CRM** is now provider-agnostic: when `automation_config` supplies an
  `endpoint` (+ `api_key`/`auth_header`), it POSTs the contact/action/details
  payload to that CRM API (`service_name="crm"`, `status="completed"`,
  `delivery="external"`). With no endpoint it falls back to the historical
  record-only behavior (`status="recorded"`, `delivery="internal"`), so plan
  items without a CRM target still work.
- **Social** external delivery is **additive**: the internal feed post is always
  written, and when `external_endpoint` (+ `external_api_key`/`external_auth_header`)
  is configured the post is also published to that surface
  (`delivery="internal+external"`).

The MasterPlan → task automation binding is already generic
(`masterplan_execution_service._automation_from_item`), so plan items can target
the CRM/social connectors with no further wiring.

**Tests:** `tests/unit/test_automation_connectors.py` — CRM record-only fallback +
external POST (payload/auth/wrapping), social internal-only + additive external
delivery, and the unsupported-type / required-content guards. (Connectors
previously had zero behavioral coverage.)

**Deferred (runtime-owned, not blocking):** a first-class `register_connector`-style
registration hook (connectors are an app-side `if/elif` ladder today) and
capability-enforced outbound I/O (allow-lists, credential vaulting, rate-limiting).
`perform_external_call` only observes; it does not gate. Tracked: `TECH_DEBT.md` →
**MASTERPLAN-CONNECTOR-RUNTIME-1**.

---

## 11. Technical Debt

Masterplan layer debt is tracked in `TECH_DEBT.md`:
- **MASTERPLAN-CONNECTOR-RUNTIME-1** — the runtime-owned connector hardening
  (first-class `register_connector` hook + capability-enforced outbound I/O) noted in
  §8 and Step 4.
- **APP-DEBT-MIGRATED-1** ("Masterplan dependency cascade + execution automation") —
  the domain roadmap row; anchor/ETA/cascade debt is closed, the residual is the
  runtime connector work above.

---

## 12. Governance Notes

- This document is the canonical reference for the Masterplan SaaS layer.
- Any changes must also update:
  - `docs/api/API_CONTRACTS.md`
  - `docs/architecture/EVOLUTION_PLAN.md`

---

## 13. Summary (Operational Truth)

The Masterplan SaaS layer currently implements **planning, locking, activation,
anchor setting, dependency-aware task execution, plan-scoped cascade/critical-path
ETA projection with continuous-time (per-task-duration) compression, and automation
binding that reaches external social/CRM/email/webhook/payment surfaces**. The
system's core promise (execution as timeline compression, then external execution)
is now represented concretely end to end. The remaining refinements are
runtime-owned hardening — a first-class connector registration hook and
capability-enforced outbound I/O — not app-level gaps.
