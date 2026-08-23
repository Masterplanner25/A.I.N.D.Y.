---
title: "Infinity Score — the three-axis model (Volume / Worth / Trajectory)"
last_verified: "2026-07-18"
api_version: "1.0"
status: draft
owner: "app-team"
---

# Infinity Score — the three-axis model

**Status: design proposal.** Captures the original design intent for what the Infinity
score should measure, reconciles it with what the code computes today, and defines the
model + rollout that would close the gap. Nothing here is built yet; it is the spec the
parked **3b-full** values decision and the **learned-recursion Phase 2** work both resolve
to. See [BUILD_PLAN.md](../architecture/BUILD_PLAN.md) and
[INFINITY_LEARNED_RECURSION_SCOPE.md](./INFINITY_LEARNED_RECURSION_SCOPE.md).

## 1. Why this doc

The canonical `master_score` (the Infinity score) is today a weighted composite of five
data-sourced KPIs in `apps/analytics/services/scoring/infinity_service.py`:

| KPI | Measures | Flavor |
|---|---|---|
| `execution_speed` | task-completion velocity vs the user's own baseline | **completion** |
| `decision_efficiency` | completion rate + ARM analysis-quality trend | **completion** |
| `masterplan_progress` | % tasks complete + days ahead/behind target | **completion** + trajectory |
| `focus_quality` | watcher session data (duration, distractions) | behavior |
| `ai_productivity_boost` | ARM usage frequency + code-quality trend | behavior |

Two structural facts fall out of this:

1. **The score is throughput-dominated.** Three of the five KPIs are completion-flavored —
   the score answers *how much did you get done* from three angles (speed, rate, progress),
   while focus and AI-leverage get one each, and **economic/outcome value gets zero**.
2. **There is a rich but orphaned metric layer beside it.** `apps/analytics/services/calculations/calculation_services.py`
   (the `/compute/*` "legacy KPI surface") holds ~18 **input-driven** formulas —
   `calculate_twr`, `calculate_effort`, `calculate_productivity`, `income_efficiency`,
   `revenue_scaling`, `monetization_efficiency`, `business_growth`, `impact_score`,
   `lost_potential`, … — including every financial one. None of them feed `master_score`.
   (The headline **"TWR"** label is a legacy alias repointed to the behavioral
   `master_score` — `main_router.py` returns `"TWR": score.get("master_score")` — so the
   flagship number carries a financial *name* but measures behavior.)

The original intent was never "measure throughput." It was to measure **both how much you
did and what it was worth** — and to model **trajectory against plan**. This doc names that
as three axes and specifies how to get there.

## 2. The three axes

| Axis | Question | One-line intent |
|---|---|---|
| **Volume** | How much did you get done? | Throughput — work completed, weighted by size/effort. |
| **Worth** | What was it worth? | Value created — realized money **+ intrinsic value + optionality**. |
| **Trajectory** | Faster or slower than planned? | Estimate-vs-actual pace: you planned X in time T — did you beat, meet, or miss it? |

A healthy Infinity score is a **balance across all three**, not a maximization of one.
Doing a lot of low-worth work off-plan should not out-score doing one high-worth thing on
schedule.

## 3. Axis-by-axis: what exists vs. the gap

### Volume — over-built; consolidate

Throughput is the dominant signal today (3 KPIs). The work here is **subtractive**: collapse
`execution_speed` + `decision_efficiency` + the completion half of `masterplan_progress`
into a single **Volume** KPI (work completed, weighted by task `estimated_hours`/size), which
frees weight for the two missing axes rather than triple-counting completion.

### Trajectory — mostly built; surface it

This one is closer than it looks. The estimate-vs-actual machinery already exists:
per-task `estimated_hours`, the plan-scoped cascade/critical-path `eta_service`
(`projection_basis="duration"`), `masterplan_progress`'s "days ahead/behind target," and
`execution_speed`'s velocity-vs-baseline. **Trajectory is currently woven into
`masterplan_progress`** rather than standing alone. The work is to **elevate it to a
first-class KPI**: `trajectory = f(planned_duration, actual_duration)` per task/plan,
normalized so *on-time* is neutral, *ahead* is positive, *behind* is negative — reusing the
ETA service as the source of "planned."

### Worth — genuinely absent; the hard axis

Nothing in the canonical score models value. This is the crux, and it is hard for a
specific reason (§4). The domain **pillars** — Search leadgen yield, Freelance realized
revenue, social engagement — were tethered in **3b-lite** as *observability* only (they flow
into the Infinity `SupportState`, informing the loop without moving the score). Promoting a
worth signal to actually move the canonical score **is** the 3b-full decision.

## 4. The Worth problem

Worth is not realized revenue. It has three components:

1. **Realized** — money actually earned (freelance revenue, etc.). Ground-truth measurable.
2. **Intrinsic** — value to the builder independent of money (a language, a runtime, a tool
   that matters even at \$0 earned).
3. **Optionality** — latent potential to create monetary opportunity later.

**Why a pure-revenue term fails — the proving case.** Nodus (the language) and aindy-runtime
have earned \$0, yet are among the highest-worth work in the system: they have real intrinsic
value and clear monetary optionality. A revenue-only worth signal would score them as
**worthless**, which is obviously wrong. Therefore 3b-full **cannot** be a hardcoded revenue
term — worth must capture value not yet (and maybe never directly) monetized.

**Only realized worth is measurable; intrinsic and optionality are estimates.** An estimate
that is *corrected by outcomes over time* is exactly what a learned model is for. So worth is
built on an **estimation ladder**:

| Rung | Source of the worth estimate | Role |
|---|---|---|
| **(a) Declared** | the user tags a task/masterplan with intended value or "\$ potential" | the **prior** — honest, subjective, available immediately |
| **(b) Outcome-anchored** | realized value where it exists (freelance revenue, a materialized opportunity) | the **label** — ground truth, sparse |
| **(c) Learned** | a model infers expected worth from work features + which past work led to realized value | the **correction** — closes the gap between declared and realized |

The mature system is **(a) prior → (b) label → (c) correction**.

## 5. The unification — 3b-full and learned-recursion are one decision

These two parked items are the same thing seen from two ends:

- **3b-full** asks: *should worth move the canonical score, and via which signal?*
- **Learned-recursion (Phase 2)** is: *how do you make worth-estimation honest instead of
  arbitrary?* — the REFLECT ridge model already scoped in
  `INFINITY_LEARNED_RECURSION_SCOPE.md` (features from `ScoreHistory`, labels from the
  matured `LoopAdjustment` ledger) is precisely the mechanism that reconciles *expected
  worth* with *realized worth* and reweights over time.

The Nodus case proves they are inseparable: you **cannot** do 3b-full with a hardcoded
revenue term (it punishes high-value unpaid work), so 3b-full **requires** the learned
expected-worth model. Conversely, learned-recursion has no canonical effect until a worth
signal is allowed to move the score. Neither ships alone.

## 6. Rollout

Mirrors the shadow → advisory → drives discipline already in flight for the REFLECT
calibrator (default-off, soak-then-flip):

```
PHASE A  measure     Add Worth (declared prior + realized outcomes) and a first-class     ✅ SHIPPED
                     Trajectory axis + a consolidated Volume axis as OBSERVABILITY next to
                     the score. Score math unchanged; the snapshot never writes master_score.
PHASE B  shadow      Compute the three-axis score in parallel; log (three_axis, current,   ✅ SHIPPED
                     realized_worth) to a ledger on each score event. Drives nothing.
PHASE C  advisory    Worth/trajectory blend into the score within the existing weight      ✅ SHIPPED
                     clamps; behavioral KPIs remain the anchor. Flag-gated (default off).
PHASE D  drives      The three-axis model IS the canonical score; learned worth-estimation
                     (rung c) drives the worth axis. Requires soak evidence + the 3b-full
                     values flip. == learned-recursion Phase 2.
```

**Phase C — shipped (structure, 2026-07-18).** When `AINDY_INFINITY_THREE_AXIS_ADVISORY` is
on (default off), the persisted `master_score` becomes the bounded Worth+Trajectory blend of
the behavioral anchor; off, it is byte-identical to the behavioral score (tested end-to-end).
Built to the §8 spec:
- **Composition engine** `apps/analytics/services/scoring/three_axis_composition.py` —
  `compose_advisory_master` blends Worth (declared prior) + Trajectory onto the behavioral
  anchor at conservative reserved weights (default 0.12 / 0.08; env-tunable via
  `AINDY_INFINITY_WORTH_WEIGHT` / `AINDY_INFINITY_TRAJECTORY_WEIGHT`) with a hard
  `BEHAVIORAL_MIN_WEIGHT=0.80` floor. **Graceful degradation:** a missing axis (no
  declarations / no estimated tasks) returns its weight to the anchor, so absent worth or
  trajectory data never drags a score — the axes can only add signal.
- **Trajectory padding guard** (§8.3) in `compute_trajectory` — dampens the ahead-of-plan
  excess when the ahead-signature is both pervasive and strong (chronic estimate padding),
  leaving genuinely-fast-but-variable users untouched. Surfaced as `raw_score` +
  `padding_penalty` for interpretability.
- **Consolidation migration path** (§8.2) — `consolidate_volume` +
  `consolidated_weight_view` express the 5→{Volume, Focus, AI-leverage}+{Worth, Trajectory}
  reweighting (sums to 1.0). Surfaced for interpretability; it does **not** yet reshape the
  persisted schema (that is Phase D) — so this PR adds no migration.
- **Advisory preview** `GET /apps/analytics/three-axis/advisory` — read-only "advisory vs.
  behavioral" comparison from current KPIs, works whether or not the flag is on, so operators
  can compare before flipping.
- The blend is flag-gated, bounded, reversible, and non-fatal (any error falls back to the
  behavioral master — scoring never breaks). Structure is in place; the **flip** to actually
  move scores stays gated on the Phase-B shadow soak supplying the initial worth weight.

**Phase B — shipped (2026-07-18).** On each `calculate_infinity_score` event, when
`AINDY_INFINITY_THREE_AXIS_SHADOW` is on (default off), the three axes are recorded next to
`master_score` in the `ThreeAxisShadowRecord` time-series ledger (app-owned table, guarded
migration `d7e8f9a0b1c2`). The hook is flag-gated and non-fatal — scoring is unchanged
whether it succeeds or fails (tested end-to-end: a real score computation writes exactly one
shadow row when on, zero when off). Soak report at `GET /apps/analytics/three-axis/shadow`
(recent records + mean-per-axis-vs-master, the divergence signal). Flip the flag on in a real
deployment to accumulate the comparison the Phase-C decision needs.

**Phase A — shipped (2026-07-18).** The three axes are computed for observation only, next to
the unchanged `master_score`:
- `apps/analytics/services/scoring/three_axis_service.py` — `compute_three_axes` (Volume =
  effort-weighted work completed; Trajectory = estimate-vs-actual pace from task
  `duration`/`time_spent`; Worth = declared prior + realized freelance revenue). Reads via the
  `sys.v1.task.get_user_tasks` snapshot (extended additively with `duration`/`time_spent`) and
  the analytics pillar adapter — no cross-app imports.
- Declared-worth prior: `IntentValueDeclaration` (app-owned table) +
  `value_declaration_service` + `POST /apps/analytics/worth/declare`,
  `GET /apps/analytics/worth/declarations`.
- Snapshot read: `GET /apps/analytics/three-axis`.
- **Invariant (tested):** computing the snapshot never creates or modifies `UserScore` /
  `master_score`. Consolidating the completion KPIs into the canonical Volume KPI (i.e.
  *changing* the score) is deferred to Phase C — Phase A only *measures* the consolidated
  Volume alongside the existing 5-KPI score.

## 7. What this changes — and what it deliberately doesn't

- **Does not** discard the behavioral KPIs — focus and AI-leverage remain; the change is
  *rebalancing* (collapse triple-counted completion into Volume) and *adding* Worth +
  Trajectory, not replacing behavior with money.
- **Does not** make the score a revenue meter — realized money is one of three worth
  components, and worth is one of three axes.
- **Keeps** per-user adaptive weights (`kpi_weight_service`) — the axes are weighted, and the
  weights still adapt; 3b-full sets the *initial* worth weight and whether learned estimation
  may move it.
- **Resolves** the "TWR names a financial metric but measures behavior" inconsistency —
  either the score genuinely reflects worth (this model), or "TWR" is retired as a metaphor.

## 8. Decisions (resolved 2026-07-16) — the Phase C spec

The five open decisions are settled. Phase C builds against these; the values call (#4)
is deliberately a soak-tunable default, not a frozen constant.

1. **Worth prior source → declared-only, first.** The Worth axis is fed by
   `IntentValueDeclaration` (the declared prior) alone at the first flip. Realized freelance
   revenue stays **observability-only** — it is already logged next to the axes in the
   Phase-B shadow ledger (`realized_revenue`), and is promoted to an outcome *label* only
   once outcome density justifies it (rung (b), a later phase). This unblocks the model
   without waiting on sparse revenue events.
2. **Volume consolidation → consolidate to one Volume KPI.** `execution_speed` +
   `decision_efficiency` + the completion half of `masterplan_progress` collapse into a
   single **Volume** KPI (effort-weighted work completed). This ends the triple-count and
   frees weight for Worth + Trajectory. Phase C must ship a **weight-migration/reset path**
   for existing per-user `kpi_weight_service` rows keyed to the retired KPIs.
3. **Trajectory anti-gaming → penalize chronic estimate padding.** Trajectory =
   `f(estimated, actual)`, on-time neutral, ahead positive, behind negative — **but** the
   ahead-of-plan reward is **dampened when a user's estimates run chronically far above
   actuals**. (Correction to the earlier draft: to always finish "ahead" you *over*-estimate
   duration — pad the estimate — since `trajectory ∝ estimated/actual`. Over-estimation, not
   under-estimation, is the gaming vector.) The guard keeps the signal honest against
   estimate inflation.
4. **Initial worth weight → conservative nudge (~10–15%), soak-tunable.** At the first
   Phase-C flip Worth carries ~10–15% of the composite; the behavioral KPIs remain the
   anchor and the flip is reversible. This is a **default, not a constant** — the Phase-B
   shadow soak (`GET /apps/analytics/three-axis/shadow`) supplies the divergence evidence
   that justifies raising it. No larger weight ships without soak data.
5. **Pooled vs per-user learned worth model → deferred to Phase D.** Not a Phase C concern
   (Phase C uses the declared prior, no learned estimation). When Phase D (learned rung (c))
   arrives: pooled model with per-user features, revisited only if it underfits — inherited
   unchanged from the learned-recursion scope.

**Phase C scope, locked by the above:** consolidate the 5 behavioral KPIs → {Volume, Focus,
AI-leverage} + add {Worth (declared prior), Trajectory (padding-guarded)}; blend Worth +
Trajectory into `master_score` within the existing weight clamps at a conservative initial
worth weight; flag-gated (default off) with a per-user weight-migration path; soak-then-flip.

## 9. References

- Current scoring: `apps/analytics/services/scoring/infinity_service.py`,
  `kpi_weight_service.py`; the orphaned calculators:
  `apps/analytics/services/calculations/calculation_services.py`,
  `apps/analytics/routes/main_router.py` (the `/compute/*` + legacy "TWR" surface).
- ETA / trajectory infra: `apps/masterplan/services/eta_service.py`, task `estimated_hours`,
  `projection_basis="duration"`.
- Pillars (3b-lite tether): `sys.v1.<domain>.get_performance_signals` →
  `apps/analytics/services/integration/dependency_adapter.py` → Infinity `SupportState`.
- The learned mechanism: [INFINITY_LEARNED_RECURSION_SCOPE.md](./INFINITY_LEARNED_RECURSION_SCOPE.md)
  (ridge model, `ScoreHistory` features, `LoopAdjustment` labels, shadow/advisory/drives).
- Roadmap + the parked decisions: [BUILD_PLAN.md](../architecture/BUILD_PLAN.md) (3b-full, Track 3).
