---
title: "Scope — Waking the Infinity Learned Recursion"
last_verified: "2026-07-17"
api_version: "1.0"
status: current
owner: "app-team"
---

# Scope — Waking the Infinity Learned Recursion

## Where this comes from

The re-verified architecture map (map v4) marked one thing on the Infinity core as
`PARTIAL`: the **REFLECT→EVOLVE recursion** — the self-improving loop the name
"Infinity" refers to. The composite score `Σwᵢfᵢ` and its per-user weights are real
and already self-adjust; what is *not* real is a **learned model**. Today's loop
adapts by hand-authored heuristics. This document scopes the first increment of
turning one of those heuristics into a trained model — the recursion's "mind."

It is a plan, not a build. The Phase 0 build section below is the concrete first PR.

## Decisions locked (2026-07-17)

| Decision | Choice | Why |
|---|---|---|
| **What to learn first** | **Calibrate REFLECT** — a learned *expected-score* model | Sharpens the loop's self-assessment; does **not** touch the KPI weights that drive the canonical score. Safest place to start. |
| **Rollout posture** | **Shadow-first → soak-then-flip** | Train + predict alongside the heuristic, log who's right vs actual outcomes, drive nothing until it demonstrably wins. Matches the durable-exec discipline. |
| **Model class** | **Interpretable, in-process** (ridge / logistic / contextual bandit, numpy) | Low-dim features + modest data; a scoring system must stay auditable. Coefficients live in an app table and are directly inspectable. No new infra. |

## Current state — the four heuristics (grounded)

All adaptation logic is **app-owned** (`apps/analytics/services/{scoring,orchestration,reasoning}/`).
None of it is a model; each is a fixed rule:

1. **Weight adaptation** — `scoring/kpi_weight_service.py::adapt_kpi_weights`. A fixed
   `±0.02` nudge whose *sign* comes from a `prediction_accuracy` threshold (≥70 up,
   ≤40 down), credit-assigned through a **hardcoded `_DECISION_TO_KPI` map**. Clamped
   to `[0.05, 0.50]`, renormalized to sum 1.
2. **Threshold/offset adaptation** — `scoring/policy_adaptation_service.py`. 25th-percentile
   low thresholds and mean-`(actual − expected)`-delta offsets over `ScoreHistory`.
3. **The decision** — `reasoning/decision_engine.py::_decide_core`. An if/else cascade
   over KPI cutoffs. `"successful_trajectory_detected"` is only a *label*; no trajectory
   is stored or learned.
4. **REFLECT's self-assessment** *(← the target)* — `orchestration/infinity_loop.py::evaluate_pending_adjustment`.
   Expected score = `master_score + OFFSET[decision_type]` (hardcoded map, `:21-26`);
   prediction accuracy = a hardcoded `0.4·outcome_match + 0.6·score_accuracy` formula
   with a hardcoded `|Δ|/25` tolerance (`:216-220`).

## The target — calibrate REFLECT

Replace the two hardcoded pieces in `evaluate_pending_adjustment` — the **expected-score
offset** and the **accuracy formula's implicit calibration** — with a learned model that
predicts the **expected master-score for a decision given its context**. A better
expectation ⇒ a better-calibrated `prediction_accuracy`, which is the signal every
*other* loop already consumes (weight adaptation, threshold offsets, strategy selection).
So calibrating REFLECT improves the whole loop **without** changing which signal moves
the canonical score — the 3b-full values decision stays parked.

### Ownership — why Phase 0 needs no runtime PR

| Piece | Owner | Access |
|---|---|---|
| The heuristic being replaced (`evaluate_pending_adjustment`) | **app** | edit in place |
| **Features** — `ScoreHistory` (per-user KPI time-series) | **app** table | direct ORM query |
| **Labels** — `LoopAdjustment` (`expected_score` → `actual_score`, `prediction_accuracy`, `loop_context`, `decision_type`) | **runtime** | already read via `sys.v1.automation.list_loop_adjustments` through `services/integration/dependency_adapter.py` |
| Model parameters | **new app table** | app-owned |
| Injection seam | `register_scheduled_job` / `register_job` in `apps/analytics/bootstrap.py` | training trigger |

The label-bearing ledger is runtime-owned, but it is **read-only reachable today** — we
do not add columns to it. Everything else is app-owned. Conclusion: **Phase 0 is entirely
app-side.** If a later phase needs a new field on the runtime ledger, that becomes a
runtime feature request — not before.

### The model

- **Form:** ridge regression per `decision_type` — `expected_score = wᵀx + b`, solved
  in-process by the normal equations with an L2 term (numpy; no new dependency —
  numpy + pgvector are already present). A contextual bandit is the upgrade path if we
  later learn the *decision* (out of scope here).
- **Features `x`:** the 5 KPI sub-scores at decision time, their short-window deltas from
  `ScoreHistory` (trend), `confidence`, `data_points_used`, and `decision_type` context.
  Low-dimensional and interpretable.
- **Label `y`:** the realized `actual_score` stamped on the matured `LoopAdjustment`.
- **Pooled, not per-user (recommended):** per-user adjustment counts are thin
  (`MIN_SAMPLES` ~10). Train one pooled model with per-user features; revisit per-user
  models only if pooled underfits. *(Open decision — see below.)*
- **Cold-start:** below a minimum sample count the model abstains and the heuristic stands.
  The flag-off path is always pure heuristic.

## Phased rollout

```
PHASE 0  shadow      train + predict alongside the heuristic; log
         (this PR)   (learned_expected, heuristic_expected, actual). Drives
                     NOTHING. Flag AINDY_INFINITY_LEARNED_SHADOW = off.
PHASE 1  advisory    learned expectation blends into prediction_accuracy within
                     the existing clamps; heuristic remains the anchor. Flag-gated.
PHASE 2  drives      learned expectation replaces the hardcoded offset; heuristic
                     is the fallback. Requires soak evidence (below) + the 3b-full
                     flip call.
```

**Flip criterion (Phase 0 → 1):** on held-out matured adjustments over a soak window,
`MAE(learned_expected, actual) < MAE(heuristic_expected, actual)` by a margin, sustained.
The shadow log *is* the evidence.

## Phase 0 — the first PR (build scope)

Entirely app-owned, default-off, reversible (flag off ⇒ today's behavior byte-for-byte).

**New app tables** (`apps/analytics/models` + guarded migration):
- `InfinityExpectationModel` — one row per `decision_type`: serialized coefficients
  (JSON), feature schema/version, `sample_size`, `trained_at`, `holdout_mae`.
- `InfinityExpectationPrediction` — the shadow ledger: `loop_adjustment_id`,
  `decision_type`, `learned_expected`, `heuristic_expected`, `actual_score` (stamped when
  the adjustment matures), feature snapshot, `created_at`. This is what proves or refutes
  the model.

**Service** — `services/scoring/expectation_model_service.py`:
- `build_features(...)` — assemble `x` from a score snapshot + `ScoreHistory` trend.
- `train(db)` — pull matured adjustments via `dependency_adapter`, join `ScoreHistory`
  features, fit ridge per `decision_type`, persist `InfinityExpectationModel`. Pure numpy;
  a `predict()` that abstains below the sample floor.
- `evaluate(db)` — learned vs heuristic MAE against actuals from the shadow ledger.

**Shadow hook** — in `evaluate_pending_adjustment`, guarded by
`AINDY_INFINITY_LEARNED_SHADOW` (default off): compute `learned_expected`, write an
`InfinityExpectationPrediction` row alongside the *unchanged* heuristic path. **No change**
to `prediction_accuracy`, weights, thresholds, or the score. When the flag is off the
function is untouched.

**Training trigger** — a registered job (`analytics.expectation_model_train`), invoked
from the existing daily recalculation job; also callable on demand.

**Read surface** — a syscall / endpoint returning `evaluate(db)` (learned MAE vs heuristic
MAE, sample counts, per-decision-type coefficients) so the soak is observable.

**Tests** — pure feature/ridge-fit unit tests (deterministic numpy), shadow-hook writes
a prediction row and does not perturb the score, flag-off is a no-op, evaluate math.
Plus the standard gate: app-profile boot, `check_app_imports`, `check_api_reference`,
single migration head.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| A learned model quietly perturbs the canonical score | Phase 0 **drives nothing**; flag-off ⇒ identical behavior; only the shadow table is written. |
| Opacity in the thing that scores you | Interpretable model; coefficients stored and exposed via the read surface. |
| Per-user data too thin to learn | Pooled model with per-user features; cold-start abstains to the heuristic. |
| Overfit / leakage | Held-out MAE is the flip criterion; features are decision-time-only (no post-outcome leakage). |
| Forces the 3b-full values decision prematurely | It does not — calibrating REFLECT never moves the canonical weights. 3b-full is only re-opened at Phase 2. |

## Open decisions (not blocking Phase 0)

- **Pooled vs per-user model** — recommended pooled first; revisit if it underfits.
- **Phase 2 flip + 3b-full** — the eventual "learned expectation drives scoring" step is
  still gated on a soak result *and* the parked 3b-full values call. Deferred by design.
  These are unified in [INFINITY_SCORE_MODEL.md](./INFINITY_SCORE_MODEL.md): this learned
  model is the mechanism that makes the **Worth axis** honest, and Phase 2 == that model's
  "drives" rung. The two parked items are one decision seen from two ends.

## References

- [INFINITY_SCORE_MODEL.md](./INFINITY_SCORE_MODEL.md) — the three-axis (Volume/Worth/Trajectory) score model this loop serves.
- Reconciled architecture map — **retired as an external artifact 2026-08-15**; the
  built-vs-asleep re-audit is folded into [BUILD_PLAN.md](../architecture/BUILD_PLAN.md).
- [`../handoffs/SOAK_AUDIT_2026-08-15.md`](../verification/SOAK_AUDIT_2026-08-15.md) — **Phase 2 must
  not flip.** The learned calibrator's apparent win (holdout MAE 0.0000 on two decision types) is
  a memorised constant: `create_new_task` and `reprioritize_tasks` have **one** distinct
  `actual_score` across all rows. Not a soak result — an idle-stack artifact.
- [BUILD_PLAN.md](../architecture/BUILD_PLAN.md) — forward roadmap (3b-full open decision).
- `apps/analytics/services/orchestration/infinity_loop.py` — `evaluate_pending_adjustment` (the target).
- `apps/analytics/services/scoring/{kpi_weight_service,policy_adaptation_service}.py` — the other three heuristics.
- `apps/analytics/services/integration/dependency_adapter.py` — the `sys.v1.automation.*` ledger seam.
