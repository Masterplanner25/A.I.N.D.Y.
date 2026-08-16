---
title: "Soak audit — the gate that could never open"
last_verified: "2026-08-15"
api_version: "1.0"
status: current
owner: "app-team"
---

# Soak audit — the gate that could never open

**Written 2026-08-15**, auditing the accumulated shadow/advisory data that four flag-gated
features have been waiting on.

**Verdict: do not flip any of them. Not because the data says no — because there is no data.**
294 three-axis records, 269 expectation predictions and 285 loop decisions are, almost entirely,
*the same measurement repeated*. The soak has been accumulating rows, not evidence.

---

## 1. What was being waited for

Five features shipped behind default-off flags with the same plan attached: *ship shadow → ship
advisory → soak → flip*.

| Flag | Feature | Recorded status before this audit |
|---|---|---|
| `AINDY_INFINITY_THREE_AXIS_SHADOW` / `_ADVISORY` | Volume/Worth/Trajectory blend | Phases A/B/C shipped; **Phase D gated on soak** |
| `AINDY_INFINITY_LEARNED_ADVISORY` | Learned REFLECT calibrator | Phases 0/1 shipped; **Phase 2 gated on soak** |
| `AINDY_SEARCH_OUTCOME_WEIGHTING` | Outcome-weighted search ranking | Built; **soak, then flip** |
| `AINDY_REASONING_NODUS_NATIVE` | Reasoning via the Nodus VM | Built, behaviour-neutral; **soak, then flip** |
| `AINDY_NEXT_ACTION_ACTING` | Bounded autonomous dispatch (FR-3) | Adopted; **soak, then flip** |

`BUILD_PLAN.md` states the premise plainly: Phase D *"needs the Phase-B shadow soak's divergence
data, not more build."* That was correct about what is needed. It was wrong about what soaking
produces here.

---

## 2. The three-axis shadow set carries no signal on two of three axes

294 records across 25 users:

| Column | Distinct values |
|---|---|
| `master_score` | 19 |
| `volume_score` | **2** |
| `worth_score` | **1** |
| `trajectory_score` | **0** — every row NULL |
| `realized_revenue` | total **0.00** |

Phase D flips a blend of Volume, Worth and Trajectory into the canonical score. **Worth is a
constant and Trajectory does not exist.** Flipping would not be adopting a validated model; it
would be blending two constants and a null into the number the whole product is judged by.

### What each axis is actually gated on — and it is not money

Corrected 2026-08-16 after reading the composition code rather than inferring from the column
names. **No axis is defined over revenue**, so "we have no revenue" is not the blocker:

| Axis | Actually computed from | Why it is empty | Needs funds? |
|---|---|---|---|
| **Volume** | completed task count / effort | 8 tasks, 2 completed | No |
| **Worth** | **declared** worth only — `compute_worth` → `100·(1−e^(−declared_total/scale))` | **`intent_value_declarations` has 0 rows** | **No** |
| **Trajectory** | estimate-vs-actual pace over tasks with **both** `duration` and `time_spent` | no completed task has both | No |

`realized_revenue` is carried in the snapshot but is **explicitly observability-only** —
`three_axis_service.py:184` says *"raw \$, NOT folded into score in Phase A"*, and the module
docstring says *"realized revenue stays observability-only."* It is not in the Worth score at all.

**The Worth blocker is a missing surface, not missing money.** `record_value_declaration` and
`list_value_declarations` are implemented and routed (`analytics_router.py:315`, `:345`), accept
`kind ∈ {monetary_potential, intrinsic, strategic}` against
`target_type ∈ {task, masterplan, project, other}` — and **have no client caller at all**
(`grep` across `client/src` returns nothing). The dead-twin shape again: working engine, no face.

**Trajectory is the self-trust declaration gap seen from the other side** — it is literally
estimate-vs-actual, the same pair `SELF_TRUST_CALIBRATION_SPEC.md` §4 found 0 of. One input
unblocks both.

---

## 3. The learned calibrator "wins" by memorising a constant

The headline comparison looks spectacular, which is what prompted a second look:

| decision_type | n | learned MAE | heuristic MAE | learned better by |
|---|---|---|---|---|
| `review_plan` | 190 | 0.2424 | 1.1969 | 0.95 |
| `create_new_task` | 35 | **0.0000** | 2.2400 | 2.24 |
| `continue_highest_priority_task` | 34 | **0.0001** | 2.8494 | 2.85 |
| `reprioritize_tasks` | 10 | *(no model)* | 1.7400 | — |

A holdout MAE of 0.0000 is not a good model. It is a warning. The target distribution explains it:

| decision_type | n | distinct `actual_score` values |
|---|---|---|
| `review_plan` | 190 | 17 |
| `create_new_task` | 35 | **1** |
| `continue_highest_priority_task` | 34 | **3** |
| `reprioritize_tasks` | 10 | **1** |

Consecutive rows are byte-identical — same features, same actual:

```
continue_highest_priority_task | learned 38.25995908681881 | heuristic 41 | actual 38.26 | [50.0, 20.0, 28.8, 50.0, 50.0]
continue_highest_priority_task | learned 38.25995908681881 | heuristic 41 | actual 38.26 | [50.0, 20.0, 28.8, 50.0, 50.0]
continue_highest_priority_task | learned 38.25995908681881 | heuristic 41 | actual 38.26 | [50.0, 20.0, 28.8, 50.0, 50.0]
```

The learned model beats the heuristic because it memorised a constant the hardcoded heuristic
(41) happens to miss. On two of four decision types the target has **one distinct value**. That is
not learning; it is a lookup table with one entry, and its apparent accuracy would evaporate the
moment the score moved.

**`review_plan` is the only type with genuine variance** — 17 distinct values over 190 rows,
learned MAE 0.24 against an actual SD of 3.16 — and even that is 190 samples of a nearly-static
system.

---

## 4. Root cause: the system is measuring a user who is not using it

The whole task table:

```
completed |  2
pending   |  6
```

Eight tasks. Zero revenue. The autonomy loop fires on schedule, reads unchanged state, recomputes
an identical score, and records it as a fresh observation. Twenty-five per day, every day, through
two power cuts and three container recreates.

**Rows accumulate; information does not.** "Soak for N weeks" silently assumed elapsed time is a
proxy for varied usage. On an idle single-user stack it is not, and the gap widens with every
passing day because each new row is a duplicate that makes the sample look stronger.

This is the same finding the specs already reached from other directions, and the convergence is
the point:

- `SELF_TRUST_CALIBRATION_SPEC.md` §4 — "**0 calibratable pairs** … this is a usage gap, not a
  build gap."
- `MASTERPLAN_DOMAIN_ENGINE_SPEC.md` — `Goal`/`GoalState` mis-parented, **0 rows**.
- `RIPPLETRACE` — "one threshold explained every empty table."

Four independent investigations, one root cause: **nothing is generating real state to measure.**

---

## 5. What this changes

**The flags are not blocked on a soak. They are blocked on usage**, and usage is not something a
flag flip, a scheduler or another week of uptime can manufacture.

Concretely:

1. **Stop describing these as soak-gated.** The status is *"cannot be validated on current data"*,
   which is a different problem with a different remedy. Left as "soak-gated," they read as nearly
   done.
2. **Phase D and Phase 2 must not flip.** Not "not yet" — flipping either would put a memorised
   constant in charge of the canonical score, and it would look like it was working.
3. **`AINDY_REASONING_NODUS_NATIVE` is the exception** and can be judged separately. It is a
   behaviour-neutral substrate swap with a Python fallback, verified end-to-end in tests. Its
   soak was about stability, not about score quality, so the argument above does not apply to it.
4. **A validity guard belongs in the flip criteria.** Any future "soak then flip" needs a minimum
   distinct-target count, not just a row count. `count(*)` was the wrong metric and it is the
   metric everything was reported against — including by me, one message before this audit.

---

## 6. Correction to a claim made in this session

I flagged that `infinity_expectation_models` had "last trained 2026-08-06 while predictions kept
accruing," and suggested a retrain trigger might not be firing.

**That was wrong.** I read `created_at` (row creation, 2026-08-06) instead of `trained_at`. All
three models retrained **2026-08-15**; the rows are updated in place. Retraining fires correctly.

The real problem is worse and in the opposite direction: the models retrain faithfully, on data
that cannot teach them anything.

---

## 7. What would actually open the gate

Mostly not a build. Use the system for real, on the loop it already measures:

- **Tasks with estimates, run start → complete.** The single highest-leverage input, and it feeds
  **three** things at once: it moves `actual_score` off its constant, fills **Trajectory**
  (estimate-vs-actual pace), and produces the first calibratable pairs for
  `SELF_TRUST_CALIBRATION_SPEC.md` §4. Needs no money and no new code.
- **Value declarations.** Worth's only input. The API exists and is routed; **the one genuinely
  missing piece is a UI to enter them** — a small, well-scoped build rather than a data problem.
- **A MasterPlan with a `goal_value`.** `master_plans` is empty.

**None of this requires revenue.** An earlier draft of this document asserted Worth was defined
over realized revenue and therefore blocked on income; that was wrong, and it pointed the remedy
at the one input the owner cannot manufacture honestly.

Rough sufficiency, a floor rather than a target: **≥30 distinct `actual_score` values per decision
type** before a learned model drives anything, and **Worth non-constant with Trajectory non-null**
before Phase D is considered.

### Do not fabricate the inputs

Worth accepts a declared number and Volume counts completed tasks, so both are trivially
forgeable, and forging them would look exactly like progress — the same failure mode as §3, where
a memorised constant reads as a 0.0000 MAE. A calibration system fed invented declarations does
not become uncalibrated; it becomes **confidently wrong**, and nothing downstream can detect it.
Declared worth in particular is a statement about intent, which is the one thing here that is only
worth recording if it is true.

**The cheapest path to unblocking the flagged features is a fortnight of genuinely using the
product**, plus one small UI for declarations — which is also what the Domain Engine, self-trust
calibration and cognitive operations specs each independently need.

---

## 8. Adjacent gap: income that is not freelance revenue

Raised by the owner 2026-08-16 and confirmed in code. `realized_revenue` is sourced **only** from
`fetch_freelance_performance_signals` — the freelance pillar's syscall
(`three_axis_service.py:189-197`). There is no representation anywhere for income arriving from
outside the freelance domain: employment, retainers, royalties, grants.

**This does not currently block any score** — realized revenue is observability-only (§2) — so it
is a product gap, not a soak blocker, and should not be conflated with one.

But it is a real gap, because the observability is then wrong rather than merely absent: a user
with substantial external income shows `realized_revenue = 0.00`, which reads as "earning nothing"
rather than "earning outside the modelled domain."

**Recording external income as freelance orders would be data fabrication** — inventing clients,
orders and payments that do not exist, corrupting the freelance pricing loop (#126 learns from
realized outcomes) along the way. Not an option.

The honest shapes, unresolved:

- **A distinct income source concept** owned by a domain that is not `freelance`, feeding the same
  Worth observability seam.
- **A `monetary_potential` value declaration** — already a valid `kind`, already accepts a number.
  Semantically it is a *declared prior*, not realized income, so this understates what actually
  happened.
- **Leave it out deliberately**, on the argument that Worth should measure value *the system
  helped create*, and exogenous salary is not that.

That third option is a real position, not a cop-out, and it is the fork worth deciding first:
**is Worth measuring your economic reality, or the value attributable to the plan?** The answer
determines whether external income belongs in the model at all.

> **Partly resolved 2026-08-16.** The owner's answer was "both" — economic reality matters to the
> plan *and* can give value to it — with the qualifier that **what happens to the money is the
> variable**: a paycheck spent by Monday and one saved for a month are the same income and a
> different situation.
>
> That separates cleanly. Attribution (did the plan produce value?) is a **flow** and belongs to
> Worth. Capacity (can I afford to run the plan?) is a **stock** and belongs to feasibility, not
> to any score. A paycheck does not make the plan more valuable; it makes it more affordable.
>
> Specced as **runway** in
> [`CAPACITY_AND_RUNWAY_SPEC.md`](./CAPACITY_AND_RUNWAY_SPEC.md), routed to the risk-posture
> input that `BUILD_PLAN.md` records as "sensed, not actuated". **Worth stays attribution-only**,
> which keeps this §8 gap open but makes it much less pressing.
