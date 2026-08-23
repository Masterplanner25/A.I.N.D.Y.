---
title: "Infinity Algorithm Support System"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Infinity Algorithm Support System - Canonical Definition & Evolution Plan

---

## 1. System Definition (Canonical)

The Infinity Algorithm Support System is the **signal, observation, and feedback infrastructure** that enables the Infinity Algorithm to function as a real system.

It is not the algorithm itself.

It is the system that:

* generates inputs (tasks)
* observes behavior (watcher)
* captures feedback (user + system)
* enables iteration over time

Without this layer, the Infinity Algorithm reduces to a **static metrics engine**.

---

## 2. Core System Role

The Support System transforms:

```plaintext
Human Activity -> Structured Signals -> Algorithm Inputs
```

And enables:

```plaintext
Observation -> Feedback -> Adjustment -> Re-execution
```

---

## 3. Core Components

---

### 3.1 Input Layer - Task System

**Source of structured execution data**

#### Implementation

* `apps/tasks/models.py`
* `apps/tasks/routes/task_router.py`
* `apps/tasks/services/task_service.py`

#### Signals Generated

* Time (`time_spent`)
* Completion (status transitions)
* Complexity (`task_complexity`)
* Skill (`skill_level`)
* AI Utilization (`ai_utilization`)
* Difficulty (`task_difficulty`)
* Priority (present but not connected)

#### Flow

```plaintext
User Action -> Task API -> Task Service -> DB -> Algorithm Input
```

#### Reality

* **Partially implemented**
* Generates valid inputs for TWR and metrics
* Dependency-aware task execution and blocked/unblocked task state are now part of the live signal layer

---

### 3.2 Observation Layer - Watcher (CRITICAL)

**Real-time behavioral observation system**

#### Source

* Runtime-owned (`aindy-runtime`): `AINDY/platform_layer/watcher_service.py`,
  `AINDY/platform_layer/watcher_contract.py`, `AINDY/routes/watcher_router.py`
  (`AINDY/watcher/` itself holds only `__init__.py` + `constants.py`) — the watcher
  moved into the runtime at the repo split (was `The Masterplan SaaS/Watcher.txt` in
  the pre-split archive).

#### Intended Capabilities

* Focus tracking (start/stop)
* Pomodoro/session tracking
* Distraction detection:

  * manual (user input)
  * automatic (system monitoring)
* Task duration and attention tracking

#### Intended Outputs

* `focus_session`
* `distraction_detected`
* `time_on_task`
* behavioral logs

#### Execution Model

* Time-based loop (polling system state)
* Potential use of system-level monitoring (e.g., active window/process tracking)

#### Reality

* **Implemented in runtime**
* Watcher signals are stored in `watcher_signals`
* `focus_quality` scoring reads `session_ended`, `distraction_detected`, and `focus_achieved`
* Remaining gap: watcher data influences loop decisions through KPI state, but does not yet modify the standalone TWR formula directly

#### Impact

Without this layer:

* The system cannot observe real execution behavior
* The algorithm operates on incomplete data

---

### 3.3 Feedback Layer - User + System

**Mechanism for behavioral adaptation**

---

#### 3.3.1 System Feedback (Implemented)

##### ARM Metrics

* `apps/arm/services/arm_metrics_service.py`
* `apps/arm/routes/arm_router.py`

Metrics:

* Execution Speed
* Decision Efficiency
* AI Productivity Boost
* Lost Potential
* Learning Efficiency

##### Behavior

* Computes performance insights
* Generates suggestions via `ARMConfigSuggestionEngine`

##### Reality

* **Partially implemented**
* Feedback exists but is:

  * advisory
  * not enforced
* Correction (2026-06-29): `ARMMetricsService` KPI output is **not** consumed by
  Infinity scoring. Infinity computes `decision_efficiency` /
  `ai_productivity_boost` independently from raw `apps.arm.public.list_analysis_results`
  rows, so ARM "system feedback" into the algorithm is weaker than implied — there
  are two parallel, unconnected ARM-derived KPI computations.

---

#### 3.3.2 User Feedback

##### Source

* Algorithm Creation Discussion

##### Intended Signals

* Engagement
* Satisfaction
* Behavioral adjustments
* Outcome evaluation

##### Types

* Explicit (user input)
* Implicit (behavior patterns)

##### Reality

* **Implemented (explicit + partial implicit)**
* `POST /scores/feedback` writes `UserFeedback`
* ARM and agent UI surfaces can submit thumbs feedback
* System behavior now emits implicit feedback signals for retries, repeated failures, latency spikes, and abandonment
* Remaining gap: richer satisfaction signals and formula-level policy learning are still missing

---

## 4. Signal Flow (Current vs Intended)

---

### Current System (Reality)

```plaintext
Task / Watcher / ARM / Agent Outcome
-> Score recalculation
-> Loop decision
-> Task reprioritization or suggestion refresh
-> Explicit feedback capture
-> Re-score
```

---

### Intended System (Canonical)

```plaintext
Task -> Watcher -> Signals -> Algorithm -> Score
     -> Feedback -> Adjustment -> Execution -> Repeat
```

---

## 5. Connection to Infinity Algorithm

---

### Inputs Feeding the Algorithm (Implemented)

* Task-derived signals:

  * time_spent
  * task_complexity
  * skill_level
  * ai_utilization
  * task_difficulty

---

### Signals Influencing Scoring (Implemented)

* Engagement
* Impact
* AI efficiency
* ARM task priority (separate system)
* memory-derived failure/success/pattern signals now influence `run_loop()` decision selection

---

### Signals Defined but NOT Fully Used

* Watcher-derived focus/distraction no longer needs a standalone TWR control path because the legacy route now delegates to Infinity; remaining work is deeper weighting and learning inside the live Infinity path
* Task priority is now adjusted by the loop, but not yet used as an input weighting term
* Broader user satisfaction / engagement input is still missing beyond explicit thumbs feedback
* Memory signals affect loop decisions, but do not yet alter KPI formulas or learned thresholding

---

## 6. System Classification

The Support System is:

> A hybrid data pipeline, observability system, and feedback infrastructure.

It currently functions as:

* Data pipeline -> implemented
* Observability -> implemented
* Feedback engine -> partial
* Support-state aggregation -> distributed across services

---

## 7. Evolution Plan

---

### Phase v1 - Input Stabilization

**Goal:** Ensure reliable data foundation

* Validate all task inputs
* Normalize metric generation
* Connect task priority to scoring

---

### Phase v2 - Watcher Implementation (CRITICAL)

**Status:** Implemented

* Watcher runtime, signal receiver, and `watcher_signals` persistence are live
* Focus tracking, distraction detection, session logging, and heartbeat signals are stored

---

### Phase v3 - Signal Integration

**Status:** Implemented partially

* Watcher outputs feed `focus_quality`
* `focus_quality` now drives loop decisions through `run_loop()`
* Remaining work:

  * broader engagement weighting
  * deeper learned weighting rather than heuristic weighting

---

### Phase v4 - Feedback Enforcement

**Status:** Implemented

* Loop decisions now produce:

  * automatic task reprioritization OR
  * persisted suggestion refresh
* Feedback is connected to execution behavior through `LoopAdjustment` + `UserFeedback`

---

### Phase v5 - User Feedback Integration

**Status:** Implemented partially

* Explicit thumbs feedback exists for ARM and agent outcomes
* Implicit feedback signals now exist for retries, repeated failures, latency spikes, and abandonment
* Explicit feedback now nudges per-user KPI **weights** (Step 5, `adapt_kpi_weights`)
* Remaining work:

  * richer satisfaction signals
  * weighting feedback directly into the KPI **score formulas** (beyond weights)

---

### Phase v6 - Full Closed Loop

**Goal:** True self-improving system

```plaintext
observe -> score -> adjust -> execute -> observe
```

* Enforce recurrence
* Remove manual-only feedback dependency

---

## 8. Technical Debt

---

### Structural

* Feedback persistence exists but weighting into score formulas is still limited
* Loop decisions are rule-based rather than learned
* Support inputs are now assembled into one snapshot for Infinity
  (`support_state.gather_support_state`, Step 1); the underlying signals still live
  in their own services (task, watcher, memory, event, observability), so the
  centralization is at the consumption/assembly layer, not the storage layer

---

### Functional

* Explicit feedback now nudges per-user KPI **weights** (Step 5,
  `adapt_kpi_weights`); remaining gap is weighting feedback directly into the KPI
  **score formulas** and richer satisfaction signals
* Request metrics and system health are observable, but not yet used directly by Infinity decisions (Step 3, runtime-gated)
* The memory-weighted loop path is heuristic; the support → decision seam now has
  behavioral coverage (Step 6, `test_support_decision_loop.py`), but the full
  DB-backed real-execution E2E remains integration-tier

---

### Conceptual

* The system is now closed-loop at the execution layer
* Remaining conceptual gap is optimization depth, not loop existence

---

## 9. Phase Mapping

| Phase | Component | Status | Required Action |
| ----- | --------- | ------ | --------------- |
| v1 | Task Inputs | Implemented | Deepen weighting |
| v2 | Watcher | Implemented | Extend coverage |
| v3 | Signal Integration | Partial | Deepen learning |
| v4 | Feedback Enforcement | Implemented | Refine policy |
| v5 | User Feedback | Partial | Expand weighting |
| v6 | Closed Loop | Implemented (MVP) | Optimize |

---

## 10. Next Steps

### Step 1 - Centralize support-system state - DONE
**Files:** `apps/analytics/services/orchestration/support_state.py` (new), `apps/analytics/services/orchestration/infinity_orchestrator.py`  
**Outcome:** Infinity receives one consistent state snapshot instead of assembling
support inputs ad hoc. `support_state.gather_support_state(db, user_id, trigger_event)`
assembles memory, KPI metrics, memory signals, system state, goals, task graph, and
social signals once into a normalized `SupportState` (with a `loop_context` view and
a `summary()` for the `loop.started` event). `infinity_orchestrator.execute` now
consumes the snapshot instead of gathering inline — behavior-preserving (identical
gathering order and the same propagate-vs-default failure semantics).

**Tests:** `tests/unit/test_support_state.py` — snapshot assembly, `loop_context`
shape, `summary()` counts, default fallbacks for optional inputs, and that core
memory failures propagate.

**Deferred:** folding `identity_boot_service` state into the snapshot (it is not
part of the orchestrator's current support gathering) — a future extension, not a
behavior change here.

### Step 2 - Feed more support metrics into loop decisions
**Files:** `apps/analytics/services/orchestration/infinity_loop.py`, `apps/analytics/services/scoring/infinity_service.py`  
**Outcome:** watcher, feedback, and execution support signals influence decisions more directly.

### Step 3 - Connect observability aggregates to support inputs - DONE (2026-07-08)
**Files:** `apps/analytics/services/integration/dependency_adapter.py`, `apps/analytics/services/orchestration/support_state.py` (app lever); `sys.v1.observability.support_metrics` (runtime, aindy-runtime >=1.6.0)  
**Outcome:** request metrics and platform health become usable support inputs, not dashboard-only outputs. The runtime exposes them via the `sys.v1.observability.support_metrics` syscall (Step 3 + Step 4 in one tenant-scoped, read-only rollup); the app fetches it through `fetch_observability_support_metrics` and threads it into `SupportState.support_metrics` → `loop_context` → the reasoning engine.

### Step 4 - Aggregate agent and async execution behavior into support metrics - DONE (2026-07-08)
**Files:** same aggregate as Step 3 (`sys.v1.observability.support_metrics`), consumed via `support_state.gather_support_state`  
**Outcome:** agent-run and async-job status distributions (plus `recall_used`/`score_computed`/`next_action_chosen` loop-event counts) are delivered by the same runtime rollup and reach the Infinity loop through the support state. Degrades to `{}` on a runtime older than 1.6.0.

### Step 5 - Weight explicit feedback into KPI calculations where appropriate - DONE
**Files:** `apps/analytics/services/scoring/kpi_weight_service.py`  
**Outcome:** explicit `UserFeedback` now affects score evolution, not just post-score
decision selection. `adapt_kpi_weights` previously learned from prediction accuracy
only; it now also applies a conservative feedback nudge — feedback tied to a
decision (via `loop_adjustment_id`) reinforces/penalizes the same KPIs that
decision maps to (`_DECISION_TO_KPI`), at half the accuracy learning rate, bounded
by the existing per-KPI `MAX_SINGLE_STEP` cap and re-normalized. The path is
additive (no feedback → identical accuracy-only behavior) and defensive (a
feedback-read failure never breaks accuracy adaptation).

**Tests:** `tests/unit/test_kpi_weight_feedback.py` — positive/negative feedback
shifts the decision's KPI weights, accuracy-only behavior is preserved, feedback
read failures are non-fatal, and unmappable feedback is ignored.

### Step 6 - Validate the memory-weighted loop end to end - DONE (app seam); full DB E2E is integration-tier
**Files:** `tests/unit/test_support_decision_loop.py`  
**Outcome:** support-layer signals are proven to change Infinity decisions. The
test drives the app-testable seam `gather_support_state` (Step 1) → `loop_context`
→ `reason()` (the same wiring `run_loop` uses) and asserts that a high-impact
memory **failure** signal from the snapshot flips the decision to `review_plan`,
a clean snapshot stays `continue_highest_priority_task`, a success signal does not
flip it, and negative **feedback** summarized by the feedback analyzer (Step 5)
flips to `recent_negative_feedback`. This ties Steps 1 + 5 + the decision engine
into one regression guard over the support → decision pipeline.

**Integration-tier (not app-profile):** the full DB-backed loop — real execution
outcome → re-score → persisted `LoopAdjustment` whose `decision_type` reflects the
signal — runs through `run_loop`/`infinity_orchestrator.execute` against Postgres
(those paths are exercised in the integration suite, not the app-profile harness).

### Ownership note (2026-06-29)

Per the apps/runtime boundary, apps consume runtime primitives through registered
syscalls/jobs; they do not edit runtime. Step ownership:

- **App-owned:** Step 5 (done), Step 1 (done — `support_state.gather_support_state`),
  Step 6 (done — app seam validated; full DB E2E is integration-tier), Step 2
  (deeper loop weighting — the loop already threads feedback/memory/system/goals/
  social into the decision engine).
- **Runtime-gated → delivered (2026-07-08):** Step 3 (observability aggregates)
  and Step 4 (agent/async execution metrics). aindy-runtime 1.6.0 exposes their
  producers as one app-facing syscall, `sys.v1.observability.support_metrics`
  (capability `execution.read`); the app lever is now wired —
  `dependency_adapter.fetch_observability_support_metrics` +
  `support_state.gather_support_state`. Closed: `TECH_DEBT.md` →
  **INFINITY-RUNTIME-HANDOFF-1** (item 3).

---

## 11. Governance Notes

* This document defines the **support layer for the Infinity Algorithm**
* All changes must align with:

  * signal flow integrity
  * closed-loop execution
* Any deviation must be documented in:

  * TECH_DEBT
  * EVOLUTION_PLAN

---

## 12. Summary (Operational Truth)

The Infinity Algorithm does not work because of formulas alone.

It works when:

> Real-world behavior is observed, converted into signals, fed into scoring, and used to continuously adjust execution.

Without the Support System:

> The Infinity Algorithm is only a measurement system.

With the Support System:

> It becomes a self-improving execution engine.
