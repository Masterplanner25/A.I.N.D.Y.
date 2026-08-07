---
title: "Self-Trust — calibration as a first-class signal"
last_verified: "2026-08-06"
api_version: "1.0"
status: current
owner: "app-team"
---

# Self-Trust — calibration as a first-class signal

**Status:** spec, not started. Written 2026-08-06.

---

## 1. The question this answers

The social-layer thread arrived at a reframe worth keeping. The interesting question is not
*"who trusts you"* — which needs other people, a graph, and attestation — but:

> **How much confidence should you place in your own predictions, commitments and estimates,
> based on your observed history?**

That is answerable with one user and no network. It also explains something the system has been
doing all along: A.I.N.D.Y. has always been better at *watching* you than at *displaying* you.
Focus quality, three-axis, expectation error, autonomy decisions, WCU — that is an instrument
panel for self-knowledge, not a profile page.

**This dissolves the peer-attestation question rather than answering it.** Attestation solves
*"why should a third party believe your number?"* If the number is a **mirror** rather than a
**credential**, no third party has to. See `SURFACE_IDENTITY_BRIEF.md` §4 for how this
collapses social tier 3.

---

## 2. Two calibrations, and the gap between them is the point

There are two different questions hiding in "was I right about myself", and they must not be
merged.

| | Compares | Means |
|---|---|---|
| **Declaration calibration** | what you *said* you'd do vs what happened | **integrity** — can you believe your own commitments |
| **Model calibration** | what the *model* predicted vs what happened | **legibility** — how predictable are you to the system |

Beating a model that has learned you chronically under-deliver is not the same as hitting a
target you set. The first is a statement about the model; the second is a statement about you.

**The divergence is its own signal:**

| | Model expected it | Model did not |
|---|---|---|
| **Hit your declaration** | **Steady** — reliable and legible | **Breakout** — you beat your own history |
| **Missed it** | **Known over-commit** — the system had you pegged | **Anomaly** — nobody saw it coming |

The diagonals carry the value.

- **Breakout** is the motivating one, and it is a genuinely different message from "task
  complete": *the model, trained on your past, said 0.4; you declared 0.8 and hit 0.75 — you
  broke your own pattern, and here is the evidence.*
- **Anomaly** is diagnostic, not merely bad. A miss neither you nor the model predicted means
  something unmodelled consumed the effort — which is exactly the trigger condition for
  emergent domain detection (`MASTERPLAN_DOMAIN_ENGINE_SPEC.md` §5a), seen from the other side.

The owner's own history supplies both cases. `The Masterplan_V4` records Phase I completing in
~12 months against a 3–5 year norm — a Breakout in retrospect. Nodus and the runtime consuming
months while appearing five times in 150k characters of planning — an Anomaly.

---

## 3. Ambition stays separate — do not collapse it

The failure mode to avoid: the safest person scores highest by making tiny commitments.

Separating **calibration** (did expectation match reality) from **ambition** (how aggressive was
the attempt) prevents it. *"I said I'd finish 10 trivial tasks and finished 10"* is high
reliability and low ambition. *"I attempted a six-month breakthrough and got 80% there"* is
imperfect calibration with real leverage. **Those must not become one number.**

The system already keeps them apart, which is the useful discovery here — see §4.

**Ambition is declared; calibration is observed.** `ambition_score` comes from the Genesis LLM
reading your plan; calibration comes from what happened. That asymmetry is a feature: you cannot
inflate calibration by talking, which is what makes it self-trust rather than self-image.

---

## 4. What already exists — audited 2026-08-06

| Signal | Mechanism | State |
|---|---|---|
| **Model calibration** | `infinity_expectation_predictions` — `learned_expected`, `heuristic_expected`, `actual_score` | **194 rows, 16 distinct users, every row scored** |
| Its models | `infinity_expectation_models` — `coefficients`, `feature_keys`, `holdout_mae` | 3 trained |
| **Ambition** | `ambition_score` (0.0–1.0) → `determine_posture()` (`apps/masterplan/services/posture.py`) | live |
| **Direction** | Volume / Worth / Trajectory (`three_axis_composition.py`) | 219 shadow records, Phase C |
| **Declaration inputs (task)** | `duration` set from `estimated_hours` at create; `time_spent` accumulated on start→complete/pause | mechanism complete |
| **Declaration inputs (plan)** | `goal_value` / `goal_unit`, Domain Engine `target_value` | schema present |

### The honest asymmetry

- Model calibration: **194 scored predictions**, attributable to users via
  `loop_adjustments.user_id`.
- Declaration calibration: **0 calibratable pairs.** 5 tasks carry an estimate, **0 carry
  `time_spent`**, so nothing overlaps. `master_plans` is currently empty and no plan has a
  `goal_value`.

**This is a usage gap, not a build gap.** `time_spent` is written at
`apps/tasks/services/task_service.py:551` and `:595`; `duration` is set at `:469` from the
syscall's `estimated_hours`. Both halves work. Estimates only became settable from the UI at
#157, so the existing data simply predates the capability — the first calibratable pair can be
produced today by creating a task with an estimate and running it start → complete.

**Consequence for sequencing:** model calibration can be computed now. Declaration calibration
needs the loop walked a few dozen times before it says anything. Ship the first, accumulate for
the second, and only then compute the divergence.

---

## 5. The unit trap — read before implementing

```
Task.duration    = estimated effort, in HOURS
Task.time_spent  = elapsed, in SECONDS
analytics TaskInput.time_spent = hours (API surface, different again)
```

A ratio that forgets the conversion is wrong by **3600** and will read as spectacular
over-delivery rather than as a bug. This mismatch is already a documented hazard in this repo;
it is repeated here because a calibration score is exactly the kind of derived number that looks
plausible while being nonsense.

**Normalise to one unit at the boundary, once, and assert it in a test.**

---

## 6. Design

### 6.1 Declaration calibration

Per completed task with both halves present:

```
ratio  = actual_effort_hours / declared_effort_hours        # both in hours
error  = |ln(ratio)|                                        # symmetric: 2x over == 2x under
score  = clamp(1 - error / ln(TOLERANCE), 0, 1)             # TOLERANCE ~ 3x
```

Log-ratio rather than a raw difference, so overrunning by 2× and finishing in half the time are
penalised equally. A raw ratio is asymmetric and quietly rewards sandbagging.

Aggregate as a **recency-weighted mean** over a trailing window. Old misses must decay, or the
score becomes a verdict rather than a mirror — the credit-score failure mode, where the number is
something people avoid looking at instead of a thing they can move.

### 6.2 Model calibration

Already computed per prediction; needs only aggregation:

```
error = |learned_expected - actual_score|
score = clamp(1 - error / MAE_BASELINE, 0, 1)      # baseline from models.holdout_mae
```

Using `holdout_mae` as the baseline means "predictable relative to how predictable this model
class usually is", not an absolute.

### 6.3 Divergence

```
divergence = declaration_score - model_score
```

Positive = Breakout territory (you are hitting declarations the model did not expect).
Negative = the model reads you better than your commitments do.

**Surface the quadrant, not the number.** "Breakout" and "Anomaly" are legible; `+0.31` is not.

### 6.4 Placement

A new signal alongside the three axes, **not** folded into `master_score`. It answers a different
question from performance and must not be blended into it — the whole point of §3 is that these
stay separable.

---

## 7. Dependencies

- **The meaningful version rides on the Domain Engine.** Task-level calibration measures
  estimate accuracy — real but small-grained. Plan-level calibration measures whether you achieve
  what you set out to, which is what self-trust actually means, and that needs `target_value`
  populated per domain (`MASTERPLAN_DOMAIN_ENGINE_SPEC.md`, phases 1–2).
- **Declaration data needs usage.** Nothing to compute until tasks carry estimates and get run.
- **Nothing here needs the social layer**, a second user, or attestation.

---

## 8. Rollout

Mirrors the established path here (three-axis, learned-recursion, goal attainment):

1. **Phase 1 — model calibration, shadow.** Aggregate the existing 194 predictions into a score.
   Record; surface nothing. Nothing else changes.
2. **Phase 2 — declaration calibration, shadow.** Compute from tasks once pairs exist. Assert the
   unit conversion in a test before anything reads it.
3. **Phase 3 — divergence + quadrant, advisory.** Compute the pair, classify, expose read-only on
   the projection payload behind `AINDY_SELF_TRUST_SHADOW`.
4. **Phase 4 — surface it.** On the Collaborator face, as quadrant language rather than a
   number. This is the first phase a user sees anything.

Phases 1–2 observe only and are safe to merge.

---

## 9. What this does not do

- Does not fold into `master_score`. Different question, separate signal.
- Does not replace ambition. §3 exists to keep them apart.
- Does not require peer attestation, a social graph, or a second user.
- Does not score plan-level attainment yet — that arrives with the Domain Engine.
- Does not decide what happens to a bad score. A mirror that only ever says "you were wrong"
  gets avoided; see §10.

---

## 10. Open questions

- **What makes a low score recoverable?** Elo works because losses are recoverable and recent
  form dominates. Window length and decay rate are the whole difference between a mirror and a
  verdict, and neither is chosen here.
- **Is the comparison base the estimate or the commitment?** A task estimate is a guess about
  effort; a MasterPlan goal is a commitment about outcome. Both are "declarations" but they mean
  different things, and the score should probably not average them.
- **Does an abandoned task count as a miss?** Not finishing is data, but treating every dropped
  task as a calibration failure punishes correctly abandoning bad work — which is a *good*
  decision the system would then be scoring as a bad one.
- **Should Breakout notify?** It is the one genuinely motivating output the system can produce.
  It is also the one most easily cheapened by firing too often.
