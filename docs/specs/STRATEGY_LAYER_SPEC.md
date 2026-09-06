---
title: "Strategy Layer Spec"
last_verified: "2026-09-05"
api_version: "1.0"
status: draft
owner: "app-team"
---

# The Strategy layer — a failable unit between a goal and a task

**Status:** DRAFT. Nothing built. Written 2026-09-05 from the owner's design question during the
first real use of a locked MasterPlan.

**Problem:** the plan has no layer that can fail. Goals succeed or don't, tasks succeed or don't,
and neither is a useful unit to learn from.

**Proposal:** `MasterPlan → Goal → Strategy → Task`, where a strategy is temporary, executable,
failable, and refined from its own outcomes.

Context: `MASTERPLAN_GOAL_ATTAINMENT_SPEC.md` (goals resolved against real signals),
`MASTERPLAN_REDESIGN_BRIEF.md` (diagnosis), `TECH_DEBT.md` →
`MASTERPLAN-GOALS-UNLINKED-1`.

---

## 1. What prompted it

The owner locked the first real MasterPlan on 2026-09-05, activated it, created a task against it
and started the task. Their observation:

> *"that means we basically just have a task timer … expecting them to start and stop it might be
> a bit much. Maybe tasks from the human's end should be more like things within the MasterPlan
> that need doing — the overall masterplan and its goals, but then you have strategies that you
> may try (temporary, executable, failable but able to be learned from and refined), and then
> tasks you need to do to execute the strategies."*

Two claims worth separating. The first — that the timer is a poor thing to ask a human for — is
about the *interaction*, and stands. It is often paired with the assumption that the timer is
therefore useless, which §2 shows is false: the value it produces is the only actual-time data
the system has. The second is a model proposal, and is what the rest of this spec is about.

---

## 2. ★ The timer feeds exactly one thing — and it is load-bearing

**The owner's read that this is "just a task timer" is right about the interaction and wrong
about the plumbing, so the obvious remedy — delete it — is the wrong one.**

`Task.time_spent` (elapsed **seconds**, written on stop at
`apps/tasks/services/task_service.py:551` and on the re-accrual path at `:595`) is the **sole
source of actual-time data in the system**. It is exposed through
`sys.v1.task.get_user_tasks` (`apps/tasks/syscalls/syscall_handlers.py:311`) and consumed by the
**Trajectory axis** of the three-axis Infinity score:

```python
# apps/analytics/services/scoring/three_axis_service.py:119
est_hours    = float(t.get("duration") or 0.0)              # estimated hours
actual_hours = float(t.get("time_spent") or 0.0) / 3600.0   # time_spent is SECONDS
ratio = min(TRAJECTORY_RATIO_CAP, est_hours / actual_hours) # >1 faster than estimate
```

Trajectory is estimate-vs-actual pace. Nothing else in the repo produces "actual". Remove
start/stop and `compute_trajectory` returns `{"score": None, "reason":
"no_estimated_completed_tasks"}` permanently — one of the three axes goes dark and never
comes back.

Three separate `time_spent`-shaped things exist; conflating them is what makes this look
vestigial:

| | what it is | who reads it |
|---|---|---|
| `Task.duration` | estimate, hours, set at creation | **Volume** axis (`three_axis_service.py:98`) |
| `Task.time_spent` | actual, **seconds**, from the timer | **Trajectory** axis (`:119`) |
| `TaskInput.time_spent` | caller-supplied hours on an API payload | the manual TWR/LHI calculators (`calculation_services.py:88`) — the dead KPI formulas, unrelated to the model field (`analytics_inputs.py:8` says so explicitly) |

### Why it still *feels* like it feeds nothing

Both three-axis flags are **default-off**: `AINDY_INFINITY_THREE_AXIS_SHADOW` and
`AINDY_INFINITY_THREE_AXIS_ADVISORY`. Phase A is observation-only and "never writes
`master_score`". So today the timer feeds a computation that runs in shadow, if enabled at all,
and changes nothing the user sees. Phase D — letting the axes drive scoring — is gated on a
real-deployment soak that has not happened.

That is a **sequencing** problem, not a dead-code problem. The consumer is built and correct;
it is switched off. The honest statement is: *the timer costs an interaction today and pays out
only after the soak.*

---

## 3. ★ The layer already exists — flattened into `tasks`

The live database (plan id 10, locked, active, `version_label = "V1"`) settles the design
question better than any argument. **Every task attached to the plan:**

```
 id |           name            | depends_on                        | status
----+---------------------------+-----------------------------------+-------------
 12 | Foundation Building       | []                                | pending
 13 | Platform Development      | [{"task_id": 12, "type":"hard"}]  | blocked
 14 | Expansion and Scaling     | [{"task_id": 13, "type":"hard"}]  | blocked
 15 | Optimization and Feedback | [{"task_id": 14, "type":"hard"}]  | blocked
 16 | Sustainability and Growth | [{"task_id": 15, "type":"hard"}]  | blocked
 17 | Fix Nodus Issues          | []                                | in_progress
```

Rows 12–16 are **not tasks**. They are the plan's five phases — `duration_months: 12` each,
straight out of `structure_json` — materialized into the task table at lock time because that
was the only table available to put them in. Row 17 is the owner's actual work, and it sits as
a **sibling of a twelve-month phase**, with nothing in the schema distinguishing "a thing I do
this afternoon" from "a year of strategic posture".

That is the whole complaint, in one query. It also explains why the plan looks like a task
timer: the only row you can act on is 17, and the only affordance a task has is start/stop.

`parent_task_id` exists on the model and is **NULL on all six rows** — the hierarchy mechanism
is present and unused.

### What Genesis produced and the schema threw away

`structure_json` (2551 bytes) is richer than the one field that got materialized:

| key | content | materialized? |
|---|---|---|
| `phases` | 5 × 12-month, name + description | **yes** → tasks 12–16 |
| `success_criteria` | 5 ("Establishment of a widely adopted ethical AI framework", …) | **no** |
| `core_domains` | 3 × name + intent | **no** |
| `risk_factors` | 5 | **no** |
| `key_assets` | 5 | **no** |
| `ambition_score` / `confidence_at_synthesis` | 0.8 / 0.9 | **no** |

**There are 0 rows in `goals` while 5 success criteria sit unqueryable in a JSON blob.** That is
`MASTERPLAN-GOALS-UNLINKED-1` seen from the other end: goals are not unlinked because nobody
wrote the link, they are empty because nothing promotes what Genesis already produced into rows.

### Table state

| layer | table | scoped to | rows |
|---|---|---|---|
| Plan | `master_plans` | `user_id`, versioned via `parent_id` | 1 |
| Goal | `goals` | **`user_id` only — no plan link** (verified in `apps/masterplan/goals.py`) | **0** |
| Goal progress | `goal_states` | `goal_id` | **0** |
| Task | `tasks` | `masterplan_id`, `parent_task_id` | 9 (6 on the plan, 3 test artifacts) |

### And Trajectory measures nothing yet

`time_spent` is **0.0 on all nine rows**, including task 17, which is `in_progress` with a
start time. It accrues only on stop (`task_service.py:551`), and `compute_trajectory` skips any
task without both `duration > 0` and `time_spent > 0`. So the axis §2 describes is correct,
wired, and currently measuring a sample of zero.

### The name `strategies` is already taken

`apps/rippletrace/strategy.py` defines `StrategyDB` on `__tablename__ = "strategies"` — RippleTrace
content-publication patterns matched against drop points via `strategy_engine`. **0 rows**, but the
table exists and the name is claimed.

Its columns are, awkwardly, almost exactly what this layer wants: `name`, `pattern_description`,
`conditions`, `usage_count`, `success_count`, `failure_count`, `success_rate`, `score`. Someone has
already modelled "a failable thing that learns from its outcomes" — for a different domain.

**Do not reuse that table.** Different owner, different lifecycle, and `extend_existing=True` on it
suggests it has already been a source of collision. This layer needs its own name —
`plan_strategies` is the obvious candidate and is unclaimed.

---

## 4. Why "failable" is the load-bearing word

A goal is too big and too slow to learn from: by the time it succeeds or fails, the information is
months old and confounded. A task is too small, and its failure usually means nothing — a task that
did not get done says more about the week than about the approach.

A strategy is the grain where a **hypothesis** lives. "Publish twice a week to build inbound" is a
claim that can be tried, abandoned, and — crucially — *repeated enough times that a success rate
means something*. That is the unit the Infinity algorithm can actually learn from, and it is
missing.

This also resolves the goal-scoping question in `MASTERPLAN-GOALS-UNLINKED-1`. Goals being
user-scoped and long-lived is **correct** if strategies are the plan-scoped layer: the goal
("reach $10k MRR") outlives plan versions, while the strategies against it churn per version.
That reading makes the current `goals.user_id`-only model right rather than wrong.

---

## 5. Proposed model

```
MasterPlan  ──┐
              ├── Strategy ──── Task
Goal      ────┘
```

A strategy references **both**: the plan it belongs to (so it churns with plan versions) and the
goal it serves (so attainment can attribute movement).

```python
class PlanStrategy(Base):
    __tablename__ = "plan_strategies"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    masterplan_id = Column(Integer, ForeignKey("master_plans.id"), nullable=False, index=True)
    goal_id       = Column(UUID, ForeignKey("goals.id"), nullable=True, index=True)

    name        = Column(String(255), nullable=False)
    hypothesis  = Column(Text, nullable=True)   # what we believe this will do, in the user's words
    status      = Column(String(32), default="proposed")  # proposed|active|paused|abandoned|succeeded
    started_at  = Column(DateTime, nullable=True)
    ended_at    = Column(DateTime, nullable=True)
    outcome     = Column(String(32), nullable=True)   # worked|did_not_work|inconclusive
    outcome_note = Column(Text, nullable=True)
```

And one nullable column on tasks:

```python
strategy_id = Column(UUID, ForeignKey("plan_strategies.id"), nullable=True, index=True)
```

Nullable on purpose: a task that belongs to a plan but no strategy stays legal, which is what the
three existing tasks are and what any quick "just do this" task should remain.

### The cheaper alternative, and why it is not enough

`parent_task_id` already exists and is NULL everywhere. Phases 12–16 could become parent tasks
and real work could hang beneath them — no new table, no migration.

**It does not carry the owner's requirement.** A task's status is `pending | in_progress |
blocked | completed`: it expresses *done or not done*. A strategy needs *worked or didn't work*,
which is a different axis — a strategy can be fully executed and still have failed, and that is
exactly the case worth learning from. Encoding "we tried this and it didn't move the needle" as
a task status means overloading `completed` or inventing a task status that only applies to some
tasks.

`parent_task_id` should still be used — for tasks under a strategy that genuinely decompose. It
is the wrong home for the layer itself.

### What is deliberately NOT on the model

**No `success_rate` / `usage_count` / `score` columns.** RippleTrace's `strategies` carries those,
and copying them is tempting and wrong here. A strategy in this layer is *one attempt*, not a
reusable pattern — its rate is computed across strategies that share a shape, not stored on the
row. Storing a denormalised rate before anything computes one is how `strategies` ended up with
0 rows and 9 columns.

**No effort or duration fields.** The timer question is separable — see §7.

---

## 6. Open questions — these need answers before building

1. **Does a strategy hang off the goal, the plan, or both?** This spec proposes both, with
   `goal_id` nullable. The alternative — goal only, plan inferred — is simpler but cannot express
   "this strategy belongs to plan v2 and its predecessor belongs to v1".

2. **Can a strategy serve more than one goal?** The model above says no (single `goal_id`). A join
   table is the honest answer if strategies routinely serve two goals, and premature otherwise.

3. **Who authors a strategy?** ~~Biggest open question~~ — §3 mostly answers it. Genesis already
   produces `phases`, `core_domains`, `success_criteria` and `risk_factors`, and lock time
   already materializes one of them into rows. The remaining question is narrower: **are the
   five 12-month phases strategies, or a tier above strategies?** They read as a tier above —
   a strategy the owner would "try and abandon" is weeks, not a year. That suggests
   `Plan → Phase → Strategy → Task`, which is one layer more than proposed, and is the single
   decision that most changes the build.

4. **What does abandoning a strategy do to its tasks?** Cascade to cancelled, orphan them back to
   the plan, or leave them? "Failable" is only useful if abandonment is cheap and obvious.

5. **Does a strategy have a target?** `goal_states` already carries `progress` and
   `success_signal`. If strategies get their own measurable target, that is a second measurement
   surface and needs to justify itself against the one that exists.

6. **Should lock time seed `goals` from `success_criteria`?** This is separable from the whole
   strategy question, is a much smaller change, and would put 5 rows in a table that has 0. It
   may be the right first move regardless of what happens to strategies.

---

## 7. The timer question — reframed by §2

My first draft of this section said the timer fed nothing and should be removed. **That was
wrong**; §2 has the evidence. Removing start/stop would delete the only actual-time source in
the system and permanently blank the Trajectory axis. The real options:

| | what it costs the user | what happens to Trajectory |
|---|---|---|
| **A. Remove start/stop** | nothing | **dies permanently** — no actual-time source remains |
| **B. Keep manual start/stop** | an interaction per task | works, if the flags are ever turned on |
| **C. Infer actual time without the timer** | nothing | works, at lower fidelity |

**C is the option worth designing.** The owner's objection is to *being asked to start and stop
a stopwatch*, not to the system knowing how long things took. Those are separable. A task
already has `start_time` and `end_time`; elapsed wall-clock between "started" and "completed" is
a cruder but free estimate, and `_apply_padding_guard` already exists in
`three_axis_service.py` precisely because self-reported pace data is untrustworthy.

If the strategy layer lands, C gets better: a strategy has a span, and tasks under it inherit a
window, so pace can be measured per-strategy without asking the human for anything.

**Recommendation: do not remove the timer as part of this work.** Decide it separately, and
decide it against the soak — if the three-axis flags are never turned on, the timer is
unjustified either way, and that is the question to answer first.

---

## 8. Migration shape

Cheap, because the tables are nearly empty: **0 goals, 1 plan, 3 test tasks.**

1. `plan_strategies` table, additive, `IF NOT EXISTS` guarded per `MIGRATION_POLICY.md`.
2. `tasks.strategy_id`, nullable, additive.
3. Optionally `goals.masterplan_id` if question 1 resolves toward plan-scoped goals; also empty.

**The one non-trivial piece is the six existing rows.** Tasks 12–16 are phases wearing a task
costume and would need to move to whatever layer wins; task 17 is a genuine task that should
end up beneath one of them rather than beside them. Six rows, one user, one plan — a hand-written
data migration, not an algorithm.

No other data migration exists to get wrong. This is the cheapest moment this change will ever
be, which is an argument for deciding it now rather than for building it hastily.

---

## 9. What this spec does not claim

It does not claim the *proposed* layer is the right shape. Open question 3 — whether phases and
strategies are one tier or two — is unresolved, and getting it wrong means migrating twice.

It does claim, on evidence rather than argument, that **the current model is flattened**: a
twelve-month phase and an afternoon's work are the same row type, distinguished by nothing. That
is not a judgement about the design; it is what the six rows on the live plan look like.

The register entry this most affects is `MASTERPLAN-GOALS-UNLINKED-1`, which §3 reframes — goals
are empty rather than unlinked, and the content to fill them is already sitting in
`structure_json`.
