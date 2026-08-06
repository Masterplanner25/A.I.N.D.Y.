---
title: "MasterPlan Domain Engine — Implementation Spec"
last_verified: "2026-08-05"
api_version: "1.0"
status: current
owner: "app-team"
---

# MasterPlan Domain Engine — Implementation Spec

**Status:** scope, not started. Written 2026-08-05. Owner chose the **structural path**
(redesign brief Option 3) over the short path (Option 2).

This implements a decision taken in the build docs and never finished, not a new idea.

> *"B) Phase thresholds configurable per Masterplan record (so users can define their own
> criteria)"* — `Masterplan Module_Plans.docx` line 5626
>
> *"You need to abstract: `Domain { name, category, threshold_type, target_value }` … That turns
> A.I.N.D.Y. from Shawn's life arc into a framework engine."* — `Masterplan_Genesis_Module.docx`
>
> *"B) Type-specific (boolean, count, numeric, composite) and normalized at calculation time"* —
> the owner's choice over normalizing everything to 0–100 upfront
>
> Order: **B → then A → then C.** *"Structure first. Then intelligence layer. Then polish."*

---

## 1. What already exists — audited 2026-08-05, not assumed

Three pieces are built. None of them are connected to each other.

| Piece | State |
|---|---|
| **Per-plan thresholds** (Layer 1) | ✅ live. The six columns are per-plan overridable and `MasterPlanInput` (`apps/analytics/routes/main_router.py:56`) accepts all of them. `/apps/compute/create_masterplan` can define a plan's own physics today. |
| **The Domain abstraction** (Layer 2) | ⚠️ built as `Goal` + `GoalState`, **mis-parented**. |
| **Live value resolvers** | ✅ `goal_attainment` resolves `tasks`, `usd`, `impressions`, `clicks`, `posts`, `playbooks` from live domain data. |

### The mis-parenting

`Goal` maps almost exactly onto the designed `Domain` — except for its parent:

| Designed `Domain` | Built `Goal` |
|---|---|
| `name`, `category` | `name`, `goal_type` |
| `metric_type` + `target_value` | `success_metric` (JSONB, unstructured) |
| `weight` | `priority` |
| `current_value` | `GoalState.progress` / `success_signal` |
| **`masterplan_id`** | **absent — `user_id` instead** |

`grep -c masterplan_id apps/masterplan/goals.py apps/masterplan/goal_state.py` → **0, 0**.

Goals hang off the *user*, so phase logic structurally cannot read them. Both tables have **0
rows**; the abstraction has never run.

### The consequence

`evaluate_phase` (`apps/masterplan/services/projection_service.py:75`) still reads the six
hardcoded columns, and **five of the six progress columns have no writer anywhere in the repo**:

```
total_wcu          writers: 1     <- wcu_service, genuinely fed
gross_revenue      writers: 0
books_published    writers: 0
platform_live      writers: 0
studio_ready       writers: 0
active_playbooks   writers: 0
```

`_requirement_met` treats an unset requirement as not-applicable, but that escape hatch never
fires on the Genesis path: `masterplan_factory.py:62` sets eleven fields and **none of the six
thresholds**, so every Genesis-locked plan inherits the model defaults (`3000 / 100000 / 3 /
True / True / 2`) — the owner's own Phase 1 numbers.

**Net:** any plan created today is gated on one real signal and five permanently-false ones, so
Phase 2 can only ever arrive via the schedule fallback.

---

## 2. Design

`Goal` becomes the Domain. Additive only — the six columns stay, per the build doc's *"Do NOT
delete old fields yet. Stabilize first."*

### 2.1 Schema (additive, nullable)

```python
# apps/masterplan/goals.py
masterplan_id = Column(UUID/Integer FK -> masterplans.id, nullable=True, index=True)
metric_type   = Column(String(16), nullable=False, default="numeric")  # numeric|count|boolean|composite
target_value  = Column(Float, nullable=True)
unit          = Column(String(32), nullable=True, index=True)   # resolver key: tasks|usd|impressions|…
```

Reuse rather than duplicate: `goal_type` **is** `category`, `priority` **is** `weight`.
`success_metric` stays for anything not modelled as a column.

`masterplan_id` is nullable on purpose — a user-scoped goal with no plan remains valid, which is
what the autonomy layer already assumes. §10 Q4 of the redesign brief asked whether Goal should
be plan physics *or* an autonomy concern; nullable makes it **both**, with no forced migration.

### 2.2 Normalization — at calculation time, per the owner's choice

```
numeric | count  ->  clamp(current / target, 0, 1)      target > 0
boolean          ->  1.0 if current else 0.0
composite        ->  weighted mean of child domains     (phase 4 — declared, not built)
unresolved       ->  None, never 0.0
```

**`None` is not `0.0`, and this is load-bearing.** The resolvers already return `None` for an
unsupported or degraded domain precisely so a phantom zero cannot be scored. An unresolved
domain must therefore be treated as *not gating* — the same rule `_requirement_met` already
applies to an unset requirement. Scoring an unresolved domain as zero would block Phase 2
forever and reproduce the current bug in new clothes.

### 2.3 Composite master index

```
index = Σ(weight_i × normalized_i) / Σ(weight_i)      over resolved domains only
```

Reported alongside the phase, not gating it.

### 2.4 Phase evaluation

```python
def evaluate_phase(plan):
    domains = plan_domains(plan)          # Goals where masterplan_id == plan.id, status active
    if domains:
        gating = [d for d in domains if d.target_value and resolved(d)]
        thresholds_met = all(normalized(d) >= 1.0 for d in gating)
    else:
        thresholds_met = <existing six-column logic, unchanged>
    ...
```

**Dual-run by construction.** A plan with no domains behaves exactly as it does today, so
nothing regresses while nothing has been migrated.

---

## 3. Feeding `current_value` — the missing writers

This is the part that makes the engine real, and it is mostly already built.

`goal_attainment` (`apps/analytics/services/integration/goal_attainment.py`) resolves a unit to a
live float:

```python
resolver(db, *, user_id, masterplan_id, _unit) -> float | None
```

Units resolvable today: `tasks`, `usd`, `impressions`, `clicks`, `posts`, `playbooks`.

**Boundary problem:** it is reachable only through an analytics HTTP route
(`analytics.goal_attainment`) — there is no syscall — and masterplan declares
`APP_DEPENDS_ON = ["identity"]`.

**Resolution:** analytics registers `sys.v1.analytics.resolve_goal_unit`, and masterplan
dispatches it by name. No new cross-app import, and it mirrors exactly how `goal_attainment`
already reaches freelance / social / rippletrace via `sys.v1.<domain>.get_goal_metric`. Adding
`APP_DEPENDS_ON += ["analytics"]` would also pass the import checker, but it couples two apps to
do what the syscall bus already does.

A scheduled job (`masterplan.domains.refresh`) walks active plans, resolves each domain's unit,
and upserts `GoalState.progress` + `last_update`. Domains with no `unit` are manual — the user
sets progress directly, which is how `platform_live` / `studio_ready`-style booleans work
without inventing a writer for them.

---

## 4. Seeding — "you eat your own architecture"

**Existing plans.** A one-time backfill converts the six columns into six domains per plan:

| Column pair | name | category | metric_type | unit |
|---|---|---|---|---|
| `wcu_target` / `total_wcu` | Work Capacity | Execution | numeric | *(wcu_service)* |
| `revenue_target` / `gross_revenue` | Revenue | Financial | numeric | `usd` |
| `books_required` / `books_published` | Book IP | Intellectual | count | — |
| `platform_required` / `platform_live` | Distribution Platform | Infrastructure | boolean | — |
| `studio_required` / `studio_ready` | Studio Infrastructure | Infrastructure | boolean | — |
| `playbooks_required` / `active_playbooks` | Playbooks | Distribution | count | `playbooks` |

Run as a **script, not a migration** — it reads app data and calls resolvers, which does not
belong in Alembic. The Alembic revision is columns only, additive, `IF NOT EXISTS` guarded.

**New plans.** `masterplan_factory` creates domains from the Genesis draft. Where the draft
carries a usable target it is used; where it does not, the domain is created with
`target_value = NULL` — declared but not gating — rather than silently inheriting someone else's
number. That is the actual fix for the inheritance bug, and it is why the factory change belongs
in this work and not in a separate Option 2.

---

## 5. Rollout

Mirrors how every other scoring change has shipped here (three-axis, learned-recursion,
goal-attainment): shadow → advisory → flip.

1. **Phase 1 — schema + read model.** Columns, `plan_domains()`, normalization, the composite
   index. Nothing reads it. Exposed read-only on the projection payload so it is inspectable.
2. **Phase 2 — resolver wiring.** `sys.v1.analytics.resolve_goal_unit` + the refresh job.
   `GoalState.progress` starts moving. Phase logic still uses the six columns.
3. **Phase 3 — shadow.** Compute the domain-driven phase alongside the live one, record both,
   change nothing. Flag `AINDY_MASTERPLAN_DOMAIN_ENGINE_SHADOW`.
4. **Phase 4 — flip.** Domain-driven phase becomes authoritative behind
   `AINDY_MASTERPLAN_DOMAIN_ENGINE`, default off, after a real soak. Composite metric_type lands
   here or later.

Phases 1–2 are safe to merge immediately; nothing observes them.

---

## 6. Compatibility and blast radius

Reference counts across `apps/`, `client/src`, `tests/`:

```
total_wcu 29 · books_required 18 · wcu_target 14 · revenue_target 9
platform_required 9 · playbooks_required 9 · studio_required 8
platform_live 5 · gross_revenue 4 · books_published 4 · active_playbooks 4
```

`total_wcu` and `wcu_target` are genuinely load-bearing (`wcu_service`, projection, the client
dashboard). **Nothing is removed in this work.** The six columns keep their meaning, keep being
written where they are written, and remain the fallback for any plan without domains. Retiring
them is a separate decision to take after the flip, with real data behind it.

---

## 7. Test plan

- **Normalization** — one case per `metric_type`, including `target = 0` and `target = None`.
- **`None` ≠ `0.0`** — an unresolved domain does not gate, and does not drag the composite index
  down. This is the regression that would otherwise recreate the current bug.
- **Dual-run** — a plan with no domains evaluates identically before and after. Assert against
  the existing `evaluate_phase` tests unchanged.
- **Backfill** — six columns in, six domains out, and phase evaluation agrees with the
  pre-backfill answer for the same plan.
- **Factory** — a Genesis lock with no usable target produces `target_value = NULL`, **not** the
  model default. This is the inheritance bug; it needs a test that fails today.
- **Boundary** — `scripts/check_app_imports.py` stays at 0 undeclared; masterplan does not import
  analytics.

---

## 8. What this does not do

- Does not delete the six columns, or change what writes `total_wcu`.
- Does not build `composite` metric_type (declared, deferred to phase 4).
- Does not add a domain-editing UI. That is Layer 2 / the build doc's **C — Experience fix**, and
  the owner's order is structure → intelligence → polish.
- Does not decide the weight calibration left open in
  `MASTERPLAN_GOAL_ATTAINMENT_SPEC.md` §7.
- Does not give `books_published` a writer. Authorship still has no publication concept, so that
  domain stays manual until it does.

---

## 9. Effort

| Phase | Scope |
|---|---|
| 1 — schema + read model | Alembic revision, model fields, `plan_domains`, normalization, composite index, tests |
| 2 — resolver wiring | analytics syscall, refresh job, `GoalState` upsert, backfill script |
| 3 — shadow | flag, dual computation, recording |
| 4 — flip | flag, cutover, composite metric_type |

Phase 1 is self-contained and reviewable on its own. Phase 2 is where the engine starts
producing data — and is the point at which a live MasterPlan begins measuring against its own
goals rather than someone else's defaults.
