---
title: "MasterPlan — Refine vs Revise, and the missing Strategy layer"
last_verified: "2026-08-23"
api_version: "1.0"
status: draft
owner: "app-team"
---

# MasterPlan — Refine vs Revise, and the missing Strategy layer

**Origin:** an owner conversation, recorded here because it names a distinction the domain has no
vocabulary for. The design below is a proposal; §1 is audited fact.

The owner's account of how the original MasterPlan formula came to exist:

> Execute against the plan → report what actually happened → compare it with what the plan assumed
> → **refine** → execute the refined version.

The point being that refinement was not a step *inside* the formula. **It was the mechanism that
produced the formula.** The plan was never a static roadmap; it was a continuously refined model of
the work, and the loop that refined it is recognisably the ancestor of the Infinity Algorithm's
own closed loop.

---

## 1. What exists today — audited 2026-08-23, not assumed

| | |
|---|---|
| Model | `MasterPlan` (`apps/masterplan/masterplan.py`) — `start_date`, `duration_years`, `target_date`, `status`, `is_active`, `is_origin`, `structure_json`, `posture`, **`version_label`** |
| Related | `Goal`, `GoalState` (the goal-attainment work), `GenesisSessionDB` |
| Verbs | `POST ""` (create) · `/lock` · `/{id}/activate` · `/{id}/activate-cascade` · `PUT /{id}/anchor` · `/feedback` · `/me/recalculate` · `GET /{id}/projection` · `/me/history` |

Two findings from that audit:

- **There is no Strategy layer.** Across `apps/masterplan/**` and all three MasterPlan specs
  (`MASTERPLAN_DOMAIN_ENGINE_SPEC`, `MASTERPLAN_REDESIGN_BRIEF`, `MASTERPLAN_GOAL_ATTAINMENT_SPEC`):
  `strategy` appears **0 times**, `revise` **0 times**, `objective` **once**. This is missing from
  the design corpus, not merely unimplemented.
- **`version_label` exists and nothing governs it.** There is a column for a plan's version and no
  operation that changes it, and no rule for when it should. A plan is created, locked, activated —
  and after that the surface offers no way to say "this is the same plan, pursued differently".

So the current model can express *that a plan changed* only by creating another plan.

---

## 2. The distinction

Three operations, not one, and they differ by **what they are allowed to change**:

| Operation | Changes | Version |
|---|---|---|
| **Update progress** | Records what happened. Task status, evidence, measurements | unchanged |
| **Refine** | *How* an objective is pursued — clarify objectives, replace an ineffective strategy, reorder or rescope tasks, absorb operational learning | **unchanged** — the plan keeps its identity |
| **Revise** | *What* the plan is trying to accomplish — add or remove a major objective, move the destination, redefine success | **new version** |

The rule, in the owner's words:

> If the change affects **how** an objective is pursued, refine. If it changes **what** the plan is
> trying to accomplish, revise and version.

**A refinement changes the current working expression of the plan without declaring that a new plan
now exists.** That sentence is the whole specification; everything below is mechanism.

---

## 3. The layer that makes the distinction possible

```
Plan          what must ultimately become true
└── Objective the major outcomes that collectively realise the plan
    └── Strategy   the chosen approach for achieving an objective   <- MISSING TODAY
        └── Task   the concrete actions that execute a strategy
```

**Strategy is the layer refinement operates on**, which is why its absence and the absence of a
refine verb are the same gap seen twice.

The owner's worked example: *publishing* is not part of the plan. It is a **strategy** for
achieving an objective — visibility, validation, audience, documenting the ecosystem. Publishing
could be replaced by live demonstrations, partnerships or documentation **without producing
MasterPlan v2**. The route changed; the destination did not.

### Why this cost something historically

> "Early on I used to confuse strategy with the overall plan… I was completing a lot of strategy,
> not necessarily completing the plan."

That is a measurement failure with a familiar shape: **effort registered against strategy while the
plan's objectives did not move**, and nothing in the model could tell the difference. It is the same
class of problem `MASTERPLAN_GOAL_ATTAINMENT_SPEC` addresses for *activity vs achievement* —
one layer up. Goal attainment asked "did completing tasks move the goal?"; this asks "did this
strategy move the objective, or should the strategy be replaced?"

---

## 4. Design sketch — deliberately thin

Not a build order. The decisions in §5 come first.

- **`Strategy`** — belongs to an `Objective`, has a status and a lifecycle including *replaced*. A
  replaced strategy is **retained**, not deleted: "we tried publishing, it did not move the
  objective" is the evidence refinement runs on.
- **`POST /apps/masterplans/{id}/refine`** — records a refinement against the current version:
  what changed, why, and which evidence prompted it. Leaves `version_label` alone.
- **`POST /apps/masterplans/{id}/revise`** — creates the next version, carrying forward objectives
  and their strategy history. This is the operation `version_label` has always implied.
- **A refinement is an event, not a mutation.** The value is the *series* — what was tried, what it
  produced, what replaced it. Recording only the latest state discards exactly the information the
  loop needs, and `score_history` already sets the precedent for append-only in this repo.

---

## 5. Open decisions — none of these are settled

1. **Does a refinement need a proposer?** The owner's original loop had the AI propose refinements
   from reported results. Whether `refine` is a user verb, an agent verb, or a user-confirmed
   agent proposal is a product decision, not a schema one.
2. **What counts as evidence?** Task completion, goal attainment deltas, Infinity sub-scores, and
   `score_history.trigger_event` are all candidates. Attainment is the obvious first input since it
   already measures achievement rather than activity.
3. **Does refinement feed the algorithm, or only the plan?** Under this repo's own sorting rule —
   *does it feed the score, the loop, or neither?* — a strategy replacement is a strong signal about
   decision quality, and `decision_efficiency` is a live KPI. Wiring that is a separate decision and
   should not be assumed by building it.
4. **Migration.** Existing plans have `structure_json` and no objectives or strategies. Whether
   those are derived, declared, or left alone for legacy plans is unresolved.

---

## 6. Why this is worth building at all

The app currently tracks execution. This is the difference between tracking execution and **helping
the user's model of the work evolve through execution** — which is what the original MasterPlan
process did by hand, and what produced the formula in the first place.

Stated as the loop:

```
Plan → Execute → Observe → Refine → Plan'
```

That is the same shape as the Infinity Algorithm's closed loop, applied to the plan rather than to
the score. The owner's observation is that the first one produced the second. Building `refine` is
putting the mechanism that generated the system back into the system.
