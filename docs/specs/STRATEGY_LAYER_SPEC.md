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

**Proposal:** `MasterPlan → Phase → Strategy → Task`, where a phase is the plan's own long arc,
a strategy is temporary/executable/failable, and strategy outcomes feed **back up** into which
phase you are in and what that phase requires.

**Decided 2026-09-05 (owner):** phases sit a tier *above* strategies —
*"execution of a strategy may change what phase you're in or what's required of a phase, but
overall it should be above a strategy."* §5 models both of those edges.

Context: `MASTERPLAN_GOAL_ATTAINMENT_SPEC.md` (goals resolved against real signals),
`MASTERPLAN_REDESIGN_BRIEF.md` (diagnosis), `TECH_DEBT.md` →
`MASTERPLAN-GOALS-UNLINKED-1`.

---

## 0. ★ This layer was already specced — read that first

`MASTERPLAN_REFINE_VS_REVISE_SPEC.md` (2026-08-23) **already names the missing Strategy layer**,
proposes `Plan → Objective → Strategy → Task`, and defines the verbs that operate on it:

> **Refine** — changes *how* an objective is pursued. Version **unchanged**.
> **Revise** — changes *what* the plan is trying to accomplish. **New version**.
>
> *"Strategy is the layer refinement operates on, which is why its absence and the absence of a
> refine verb are the same gap seen twice."*

This spec did not know that when it was written, which is an instance of the repo's own dominant
defect shape applied to its docs — a second surface built beside a working one. **The two are
now reconciled here rather than left to diverge**, and the model in §5 has changed as a result.

Division of labour going forward:

| | |
|---|---|
| `MASTERPLAN_REFINE_VS_REVISE_SPEC` | the **verbs** — refine, revise, the append-only refinement series |
| this spec | the **nouns and the evidence** — what exists in the live schema, phases, and the migration |

The owner's answers of 2026-09-05 (§6, questions 7–8) resolve **open decision 1** of the
refine/revise spec. That resolution is recorded in both documents.

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

Both three-axis flags are default-off **in code** — but not on this stack. Verified 2026-09-06:
`AINDY_INFINITY_THREE_AXIS_SHADOW=1` is set (`.env:117`), so the shadow ledger **is** recording;
`AINDY_INFINITY_THREE_AXIS_ADVISORY` is unset, so the axes still never touch `master_score`.
Phase A is observation-only by design. Phase D — letting the axes drive scoring — is gated on a
real-deployment soak (`SOAK-THEN-FLIP-1`, P1) that has not happened.

So the timer's value is being *recorded* and is not yet *used*. That is the intended stage of
"ship shadow → ship advisory → soak → flip", not a bug.

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

### ★ "Phase" already exists three times, and they disagree

The owner's tiering decision collides with machinery that is already there. Three separate
representations of *phase* live on this one plan, none of them linked to each other:

| # | where | form | who advances it |
|---|---|---|---|
| 1 | `structure_json["phases"]` | 5 named phases, description + `duration_months: 12` | nothing — inert JSON |
| 2 | tasks 12–16 | those same 5, as task rows in a hard-dependency chain | task status transitions |
| 3 | `master_plans.phase` | an **Integer**, currently `1` | `evaluate_phase()` via `wcu_service` |

Representation 3 is the only one that *moves*, and it is the one to look at:

```python
# apps/masterplan/services/projection_service.py — evaluate_phase()
thresholds_met = (
    _requirement_met(plan.total_wcu,        plan.wcu_target)          # 0 vs 3000
    and _requirement_met(plan.gross_revenue, plan.revenue_target)     # 0 vs 100000
    and _requirement_met(plan.books_published, plan.books_required)   # 0 vs 3
    and _flag_met(plan.platform_required,   plan.platform_live)       # required, not live
    and _flag_met(plan.studio_required,     plan.studio_ready)        # required, not ready
    and _requirement_met(plan.active_playbooks, plan.playbooks_required)  # 0 vs 2
)
if thresholds_met: return 2
if now >= phase_end: return 2      # phase_end = start + duration_years × 365  → 5 years
return 1
```

Two things about this:

**It returns only 1 or 2.** The plan Genesis authored has five phases. The advancing mechanism
cannot represent them.

**Every threshold is a column default.** `wcu_target=3000`, `revenue_target=100000`,
`books_required=3`, `platform_required=True`, `studio_required=True`, `playbooks_required=2` are
all `Column(..., default=...)` in `masterplan.py:57-63` — nobody chose them for this plan. They
are milestones from an earlier product shape (books, a studio, playbooks). The live plan is about
ethical AI frameworks and partnerships and mentions none of them.

So the live plan advances from phase 1 to phase 2 when it has **published three books and opened
a studio** — or, failing that, in **five years**. That is the only phase progression the system
currently performs.

Five of the six progress columns also have no writer anywhere in the repo; `_requirement_met`
already documents this and treats an unset requirement as satisfied to keep the gate reachable.
Only `total_wcu` is genuinely fed.

### And "goal" exists three times too, with zero rows in the goals table

| where | value |
|---|---|
| `goals` table | **0 rows** |
| `master_plans.goal_value` / `goal_unit` / `goal_description` / `anchor_date` | `1000000` / `USD` / `"Financial Freedom"` / `2030-12-31` — deliberately set via the anchor route, these columns are nullable with no default |
| `structure_json["success_criteria"]` | 5 criteria, unmaterialized |

The one the user actually declared is the scalar set on the plan. The table built to hold goals
is empty, and the five criteria Genesis synthesized are unqueryable.

This is the repo's dominant defect shape — a working mechanism beside a dead twin — sitting on
the plan's spine, in triplicate.

### Table state

| layer | table | scoped to | rows |
|---|---|---|---|
| Plan | `master_plans` | `user_id`, versioned via `parent_id` | 1 |
| Goal | `goals` | **`user_id` only — no plan link** (verified in `apps/masterplan/goals.py`) | **0** |
| Goal progress | `goal_states` | `goal_id` | **0** |
| Task | `tasks` | `masterplan_id`, `parent_task_id` | 9 (6 on the plan, 3 test artifacts) |

### ★ Trajectory measured something for the first time — 2026-09-06

The owner completed task 17 an hour after starting it, which produced the **first row in the
system's history with both an estimate and an actual**. Running the axis live against the plan
owner:

```json
compute_trajectory → {"score": 53.82, "raw_score": 53.82, "padding_penalty": 0.0,
                      "tasks_measured": 1, "mean_pace_ratio": 1.076,
                      "ahead": 1, "on_time": 0, "behind": 0}
compute_volume     → {"score": 2.47, "completed_count": 1, "effort_hours": 1.0}
```

Estimated 1.0 h, actual 0.929 h — 7.6% ahead, scoring just above the 50-point neutral. §2 is no
longer an argument from code reading: **the timer's value flowed end-to-end into a real axis
score.** Deleting start/stop would have taken this with it.

(Volume sees only one task because tasks 3, 4 and 8 belong to a different user.)

### …and the same measurement undercuts the timer

`time_spent` is **3344.462676 s**. `end_time − start_time` is **3344.462676 s**. The delta is
`0.000000`.

For an uninterrupted task these are identical *by construction* — the timer accrues
`now − start_time` on stop (`task_service.py:551`, `:595`), which is the same subtraction the
database could do for free. They diverge only when a task is **paused and resumed**: then
`time_spent` sums the worked intervals while wall-clock includes the gaps.

So the honest position on the single real datum the system has: the interaction the owner
objects to produced a number that required no interaction at all. The timer earns its keep only
on interrupted work — which is a real case, but is not the one being paid for here.

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

Everything the plan currently has is either too slow or too small to learn from:

| layer | horizon | what its failure tells you |
|---|---|---|
| Goal | years ("Financial Freedom", 2030) | almost nothing, and far too late |
| Phase | **12 months** on this plan | that a year went badly, confounded by everything |
| Task | hours | that you had a bad week — not that the approach was wrong |

Adding phases as a tier (§5) does not fix this on its own; **a 12-month phase is the second-worst
unit to learn from in the table.** That is the argument for a strategy sitting beneath it.

A strategy is the grain where a **hypothesis** lives. "Publish twice a week to build inbound" is a
claim that can be tried, abandoned, and — crucially — *repeated enough times that a success rate
means something*. It is the only proposed layer whose failure is both cheap and informative, and
it is the one the Infinity algorithm could actually learn from.

This also resolves the goal-scoping question in `MASTERPLAN-GOALS-UNLINKED-1`. Goals being
user-scoped and long-lived is **correct** if strategies are the plan-scoped layer: the goal
("reach $10k MRR") outlives plan versions, while the strategies against it churn per version.
That reading makes the current `goals.user_id`-only model right rather than wrong.

---

## 5. Proposed model — two axes, not one chain

The first draft of this section made `Phase` the parent of `Strategy`. **The owner's 2026-09-05
answer breaks that:**

> *"Maybe some things move phases — maybe some things get done at the same time."*

A strategy that can move between phases without changing what the plan is trying to achieve is
not *owned* by a phase. And Genesis already emits both axes separately:

| Genesis output | axis | count on the live plan |
|---|---|---|
| `phases` | **when** — time-boxed segments of the arc | 5 × 12 months |
| `core_domains` (name + intent) | **what** — the outcomes | 3 |
| `success_criteria` | how you know the outcomes happened | 5 |

`core_domains` are objectives in everything but name — *"Ethical AI Framework — to establish
guidelines and standards for ethical AI development and deployment."* That is exactly the
`Objective` layer `MASTERPLAN_REFINE_VS_REVISE_SPEC` proposes, already being generated and
currently rendered only as read-only text in `GenesisDraftPreview.jsx:24`.

So the model is two axes crossing at the strategy:

```
MasterPlan
  ├── Objective   "what must become true"   ← Genesis core_domains (3)
  │     └── Strategy   "how we're trying"   ← temporary, failable
  │           └── Task
  └── Phase       "when"                    ← Genesis phases (5 × 12mo)
          ↑
          └─ a Strategy is SCHEDULED INTO a phase; it is OWNED by an objective
```

A strategy therefore carries **two references with different meanings**:

- `objective_id` — **ownership**. Changing it changes what the strategy is for. Rare.
- `phase_id` — **scheduling**. Changing it is the ordinary act of replanning, and is precisely a
  **refine** under the existing spec: the route changed, the destination did not.

That single distinction is what makes "some things move phases" a cheap, expected operation
rather than a plan rewrite.

### ★ "Some things get done at the same time" is about execution, not scheduling

An earlier draft read this as *concurrency* — two strategies sharing a phase — and concluded the
dependency chain on tasks 12–16 had to go. **Corrected by the owner 2026-09-05; that was wrong on
both counts.** The chain stays (§8), and the real point is divergence between what was planned
and what actually happened:

> *"A human can plan to write a book and plan to write articles — but might only write the
> articles. Or vice versa: they may plan to write only the articles and end up writing both.
> Something like that would affect the phases of the plan, and is what would lead to a refine
> and/or a revise."*

Two failure modes, and **the model can express neither**:

| what happened | today | what it actually means |
|---|---|---|
| Planned the book, wrote only the articles | the book task sits `pending` forever | the book was **displaced**, not failed — you chose differently |
| Planned only articles, wrote a book too | **no record exists at all** | the plan under-described reality |

The second is the more damaging. A strategy nobody planned has nowhere to be recorded, so the
single most informative thing that can happen — *you did something the plan never anticipated,
and it worked* — leaves no trace. That is the same class of blindness as
`MASTERPLAN_GOAL_ATTAINMENT_SPEC`'s activity-vs-achievement gap, one layer up.

Two fields carry it:

```python
# on PlanStrategy
origin = Column(String(16), default="planned")   # planned | emergent
#   planned  — declared up front, in the plan
#   emergent — it just happened; recorded after the fact

status = Column(String(32), default="proposed")
#   ... | abandoned  — tried it, it did not work        (a result)
#       | displaced  — never tried; something else was done instead   (a CHOICE)
```

`abandoned` and `displaced` must not be collapsed. "We tried publishing and it did not move the
objective" and "we never published because we did the partnership instead" are different pieces
of evidence, and a success-rate computed over a set that mixes them is meaningless.

### Divergence is what decides refine vs revise

This gives the system a **derivable** proposal rule, which is what makes Q8's "the system
detects and proposes" mechanical rather than aspirational:

| divergence | serves an existing objective? | verb |
|---|---|---|
| a planned strategy was displaced | — | **refine** — the route changed |
| an emergent strategy succeeded | yes | **refine** — a route nobody wrote down |
| an emergent strategy succeeded | **no** | **revise** — the plan is now aiming somewhere it does not say |

That last row is the one worth building for. An emergent strategy with no home objective is the
system noticing that *what you are actually doing has outgrown what your plan says you are doing*
— and under `MASTERPLAN_REFINE_VS_REVISE_SPEC`'s rule ("changes **what** the plan is trying to
accomplish → revise and version") that is precisely a revise trigger.

### The advance/amend edges, restated

- **advance** — a phase's work is complete, so the phase can close.
- **amend** — an outcome changes what remains to be done, without closing the phase.

Both are now *proposals*, not state changes. See the resolved questions 7 and 8 in §6: phase
completion opens a **refine**, and the refine is what actually moves anything.

### `plan_phases`

```python
class PlanPhase(Base):
    __tablename__ = "plan_phases"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    masterplan_id = Column(Integer, ForeignKey("master_plans.id"), nullable=False, index=True)

    ordinal     = Column(Integer, nullable=False)      # 1..N — the arc order
    name        = Column(String(255), nullable=False)  # "Foundation Building"
    description = Column(Text, nullable=True)
    duration_months = Column(Integer, nullable=True)   # Genesis supplies 12

    status     = Column(String(32), default="pending")  # pending|active|complete
    entered_at = Column(DateTime, nullable=True)
    exited_at  = Column(DateTime, nullable=True)

    # ★ NOT an exit_criteria column. See §6 Q7 — the owner's definition of an exit
    # criterion is "are the things that are supposed to be done in that phase complete",
    # which is a QUERY over the strategies scheduled into the phase, not a stored predicate.
    # Storing a declared criterion beside the work it duplicates is how master_plans ended
    # up with six threshold columns nobody set.
    #
    # An optional free-text `exit_note` may earn its place later for conditions the work
    # cannot express ("wait for the grant decision"). It should be added when such a case
    # actually appears, not in anticipation of one.
```

**There is deliberately no `exit_criteria` column.** The current design asks one global question
("has this plan published 3 books?") of a plan with five distinct phases; the fix is not to ask
five stored questions instead, but to stop storing the question at all — a phase is complete when
its scheduled strategies are.

### `plan_strategies`

```python
class PlanStrategy(Base):
    __tablename__ = "plan_strategies"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    masterplan_id = Column(Integer, ForeignKey("master_plans.id"), nullable=False, index=True)
    # ★ Two references, different meanings (§5). objective_id is OWNERSHIP — changing it
    # changes what the strategy is for, and is rare. phase_id is SCHEDULING — changing it is
    # ordinary replanning, and is exactly a `refine` under MASTERPLAN_REFINE_VS_REVISE_SPEC.
    objective_id  = Column(UUID, ForeignKey("plan_objectives.id"), nullable=True, index=True)
    phase_id      = Column(UUID, ForeignKey("plan_phases.id"), nullable=True, index=True)
    goal_id       = Column(UUID, ForeignKey("goals.id"), nullable=True, index=True)

    name       = Column(String(255), nullable=False)
    hypothesis = Column(Text, nullable=True)   # what we believe this will do, in the user's words
    status     = Column(String(32), default="proposed")  # proposed|active|paused|abandoned|succeeded
    started_at = Column(DateTime, nullable=True)
    ended_at   = Column(DateTime, nullable=True)

    outcome      = Column(String(32), nullable=True)  # worked|did_not_work|inconclusive
    outcome_note = Column(Text, nullable=True)

    # NOTE: the draft carried a `phase_effect` JSONB here to record advance/amend. Dropped —
    # MASTERPLAN_REFINE_VS_REVISE_SPEC already establishes that "a refinement is an event, not
    # a mutation", append-only, with `score_history` as the in-repo precedent. The effect of a
    # strategy on a phase belongs in that refinement series, not denormalised onto the cause.
```

A `plan_objectives` table is implied by `objective_id` and is **specced in
`MASTERPLAN_REFINE_VS_REVISE_SPEC`**, not here. It seeds from Genesis's three `core_domains`
(name + intent), which are already generated and currently only displayed.

`masterplan_id` is kept alongside `phase_id` so strategies churn with plan versions even if a
phase is later reshuffled; `goal_id` stays nullable so a strategy need not claim a goal.

### `tasks`

```python
strategy_id = Column(UUID, ForeignKey("plan_strategies.id"), nullable=True, index=True)
phase_id    = Column(UUID, ForeignKey("plan_phases.id"),     nullable=True, index=True)
```

Both nullable. A task with neither is a plain to-do and stays legal — that is what "Fix Nodus
Issues" is today, and it should not become invalid.

### What this deprecates

`master_plans.phase` and the six threshold columns (`wcu_target`, `revenue_target`,
`books_required`, `platform_required`, `studio_required`, `playbooks_required`) become dead once
phases own their exit criteria. **Do not drop them** — `MIGRATION_POLICY.md` is additive-only.
Mark them deprecated, stop reading them, and leave the columns.

`evaluate_phase()` and its `wcu_service` caller would need rewriting against `plan_phases`, not
deleting; the WCU computation itself is fine, it is the gate that is wrong.

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

## 5b. ★ What the layer unlocks that nothing else can: attribution

Added 2026-09-07. The case for this layer above is about *learning* — a failable unit. There is a
second case, and it is more concrete.

The owner, on the qualitative half of a plan:

> *"You can explain things, but you still need something to actually measure/work against."*

This repo already built the unit. `MasterPlan.total_wcu` — Work Complexity Units — accumulates
the complexity of completed tasks and is live: `total_wcu = 2` on 2026-09-07, from two completed
tasks. It is the closest thing here to a universal measure of work done.

**It cannot be pointed at a goal, because work has no purpose attached to it.** `total_wcu` is a
column on `master_plans`; a task carries `masterplan_id` and nothing else. So WCU can report that
you worked. It can never report that you worked *on this*.

That is the same gap §3 describes from the other side — a twelve-month phase and an afternoon's
task are the same row type — expressed as a measurement failure rather than a modelling one:

| with today's model | with `task -> strategy -> objective` |
|---|---|
| "the plan is 40% worked" | "the ethical-AI-framework objective is 40% worked" |
| every goal reports the same number | each objective reports its own |
| a qualitative criterion is unmeasurable | it is measurable *as the work done against it* |

That last row is the useful one. "Establish a widely adopted ethical AI framework" has no natural
number — but the work toward it does, and attributing work to purpose is the only thing standing
between the two.

**Consequence for sequencing.** Two items that look independent are downstream of this one:

- Seeding `goals` from `structure_json["success_criteria"]` produces five permanently-unresolved
  goals until attribution exists (`MASTERPLAN_GOAL_ATTAINMENT_SPEC` §4b).
- Adding `wcu` to the goal-attainment unit registry is safe *only* while there is one goal per
  plan; with several it reports the same plan-wide figure for each, which reads as five goals
  progressing identically.

Neither is blocked on a decision about *them*. Both are blocked on this layer.

---

## 6. Open questions — these need answers before building

1. **Does a strategy hang off the goal, the plan, or both?** This spec proposes both, with
   `goal_id` nullable. The alternative — goal only, plan inferred — is simpler but cannot express
   "this strategy belongs to plan v2 and its predecessor belongs to v1".

2. **Can a strategy serve more than one goal?** The model above says no (single `goal_id`). A join
   table is the honest answer if strategies routinely serve two goals, and premature otherwise.

3. ~~**Are phases strategies, or a tier above?**~~ **RESOLVED 2026-09-05 (owner): a tier above.**
   *"Execution of a strategy may change what phase you're in or what's required of a phase, but
   overall it should be above a strategy."* Modelled in §5 as `plan_phases` plus the
   advance/amend edges. This was the decision that would have cost a double migration.

4. **What does abandoning a strategy do to its tasks?** Cascade to cancelled, orphan them back to
   the plan, or leave them? "Failable" is only useful if abandonment is cheap and obvious.

5. **Does a strategy have a target?** `goal_states` already carries `progress` and
   `success_signal`. If strategies get their own measurable target, that is a second measurement
   surface and needs to justify itself against the one that exists.

6. **Should lock time seed `goals` from `success_criteria`?** Separable from the whole strategy
   question, much smaller, and would put 5 rows in a table that has 0. Complicated slightly by
   §3: the user's *actual* declared goal ("Financial Freedom", $1M, 2030-12-31) lives in scalar
   columns on the plan, not in `goals`. Seeding from `success_criteria` without reconciling that
   gives you a goals table that disagrees with the plan header.

7. ~~**What shape is `exit_criteria`?**~~ **RESOLVED 2026-09-05 (owner):** *"Are the things that
   are supposed to be done in that phase complete — but the system should say 'you seem to be
   done early with this phase'."*

   So an exit criterion is **not a stored predicate at all**. It is a query over the strategies
   scheduled into the phase. The `exit_criteria` JSONB column proposed in the first draft is
   dropped (§5) — storing a declared criterion beside the work that already expresses it is how
   `master_plans` acquired six threshold columns nobody set (§3).

   The second half is the harder half: **"you seem to be done early"** is a detection, and it
   fires *before* anyone has said the phase is over. That makes phase completion a **proposal**,
   which is what Q8 answers.

8. ~~**Who decides a phase advanced — the system or the human?**~~ **RESOLVED 2026-09-05
   (owner):** *"A bit of both really. A phase being completed should trigger something like a
   review/refine of the plan — especially if you finish some things quicker than you thought.
   Maybe some things move phases, maybe some things get done at the same time."*

   **The system detects and proposes; the human confirms; and the confirmation opens a refine
   rather than flipping a status.** Phase completion is an *event that starts a conversation*,
   not a state transition.

   This resolves **open decision 1 of `MASTERPLAN_REFINE_VS_REVISE_SPEC`** ("Does a refinement
   need a proposer? … whether refine is a user verb, an agent verb, or a user-confirmed agent
   proposal is a product decision"). The answer is **user-confirmed agent proposal**, and phase
   completion — especially *early* completion — is the first concrete trigger for it.

   Three consequences worth stating:

   - The plan already has the conversational surface for this. Genesis is where a plan is
     authored; a phase-completion review is the same kind of session against an existing plan.
   - "Some things move phases" is a `phase_id` change on a strategy — a **refine**, version
     unchanged. "Some things get done at the same time" is *not* about concurrent scheduling; it
     is about execution diverging from the plan, and it is what feeds the refine/revise decision.
     See §5.
   - Finishing early is the **signal**, not a nuisance. Trajectory already measures
     estimate-vs-actual pace (§3) and the live plan's first datum was 7.6% ahead — the same
     number that would trigger a review is the one already feeding the score.

9. **Do the 12-month phase durations mean anything?** Genesis emitted `duration_months: 12` five
   times, which reads as an even split of the 5-year horizon rather than a considered estimate.
   If phases carry dates, they inherit that arbitrariness; if they carry only order, they don't.

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

**C is the option worth designing, and 2026-09-06 supplies the evidence.** On the only real
measurement in the system, `time_spent` and `end_time − start_time` agreed to six decimal places
(§3). The owner's objection is to *being asked to run a stopwatch*, not to the system knowing how
long things took — and for uninterrupted work those are the same number.

A task already has `start_time` and `end_time`. `_apply_padding_guard` already exists in
`three_axis_service.py` precisely because self-reported pace data is untrustworthy, so the
fidelity loss from inference is smaller than it looks.

The one case inference genuinely loses is **paused work**: `time_spent` sums worked intervals,
wall-clock includes the gaps. Whether that matters is an empirical question nobody can answer
from one task.

If the strategy layer lands, C gets better still: a strategy has a span, tasks under it inherit a
window, and pace becomes measurable per-strategy without asking the human for anything.

**Recommendation: do not remove the timer as part of this work** — it is now demonstrably load-
bearing, not speculatively so. But do not defend it on those grounds either: the same datum shows
the number was free. Decide it separately, against two questions in order — will the three-axis
flags ever be turned on, and does paused work happen often enough to pay an interaction for.

---

## 8. Migration shape

Cheap on paper — **0 goals, 1 plan, 9 tasks (6 on the plan)** — with one piece that needs care.

1. `plan_phases` and `plan_strategies` tables, additive, `IF NOT EXISTS` guarded per
   `MIGRATION_POLICY.md`.
2. `tasks.strategy_id` and `tasks.phase_id`, nullable, additive.
3. Optionally `goals.masterplan_id` if question 1 resolves toward plan-scoped goals; also empty.

**The six existing rows are the non-trivial piece, and they need a human, not an algorithm:**

- Tasks 12–16 become `plan_phases` rows (`ordinal` 1–5, seeded from `structure_json["phases"]`,
  which still holds the descriptions and durations).
- **Their hard-dependency chain 12→13→14→15→16 must be PRESERVED, not discarded.** An earlier
  draft said to drop it. That was wrong, and verifying it showed why: the chain feeds
  `sys.v1.tasks.get_graph_context` → `eta_service._scope_plan_from_graph`, which derives
  `critical_depth` (the longest remaining dependency chain, `eta_service.py:159`) and uses it in
  `_project_days` to set a **sequential floor** on the ETA:

  ```python
  sequential_days = (critical_depth / chain_rate) if (critical_depth > 1 and chain_rate > 0) else 0.0
  ```

  Drop the chain and `critical_depth` collapses to 1, the sequential floor vanishes, and the plan
  projects as if all five phases could be done at once. `dependency_cascade.py:87` reads it too.
  The phase order is load-bearing — carry it onto `plan_phases` as ordering **plus** an explicit
  dependency edge, not as `ordinal` alone.
- Task 17 ("Fix Nodus Issues", now `completed`) gets `phase_id` = phase 1 and stays a task. It is
  the only row in the six that was ever meant to be one — and it is now also the system's only
  Trajectory sample (§3), so it must survive the migration intact.
- The five phase-rows should be **deleted, not archived** — they are not work, were never
  actionable, and leaving them keeps the ambiguity this whole spec is about.

Objectives seed separately from `structure_json["core_domains"]` (3 rows) per
`MASTERPLAN_REFINE_VS_REVISE_SPEC`.

One user, one plan, six rows. Write the migration by hand and read it before running it.

**Deprecations, not drops.** `master_plans.phase` and the six threshold columns stop being read
(§5). Additive-only policy: leave the columns in place. `evaluate_phase()` is rewritten against
`plan_phases`, and `wcu_service`'s WCU computation is untouched — it is the gate that is wrong,
not the arithmetic.

**Order matters.** Nothing should read `plan_phases` until the six rows have moved, or the plan
will briefly have five phases in one table and five phases-as-tasks in another — which is the
condition §3 is complaining about, added to rather than removed.

## 9. What this spec does not claim

It does not claim the *proposed* layer is the right shape. Questions 3, 7 and 8 are resolved;
1, 2, 4, 5, 6 and 9 are not, and question 6 (reconciling the plan's scalar goal columns with an
empty `goals` table) is the one most likely to bite.

It also no longer claims to be the primary document for this layer. `MASTERPLAN_REFINE_VS_REVISE_SPEC`
got here first (§0); this spec supplies the live evidence, the phase axis and the migration.

It does claim, on evidence rather than argument, that **the current model is flattened**: a
twelve-month phase and an afternoon's work are the same row type, distinguished by nothing. That
is not a judgement about the design; it is what the six rows on the live plan look like.

The register entry this most affects is `MASTERPLAN-GOALS-UNLINKED-1`, which §3 reframes — goals
are empty rather than unlinked, and the content to fill them is already sitting in
`structure_json`.
