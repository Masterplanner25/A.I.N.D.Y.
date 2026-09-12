---
title: "MasterPlan Goal Attainment Spec"
last_verified: "2026-09-07"
api_version: "1.0"
status: current
owner: "app-team"
---

# MasterPlan Goal Attainment — Implementation Spec

**Status:** Phases 0 and 1 **shipped** (#173, #174, #178). Phases 2–3 not started.
Written 2026-08-01, status refreshed 2026-08-05 against the code.
**Problem:** nothing moves the MasterPlan except activity and elapsed time.
**Approach:** resolve declared goals against real domain signals, on read, via syscalls.
**Scope:** deliberately the *star* model — feed the plan better. Not the hub rewrite.

Context: `MASTERPLAN_REDESIGN_BRIEF.md` (diagnosis), `INFINITY_ALGORITHM_SUPPORT_SYSTEM.md`
(signal architecture).

---

## 1. The problem, precisely

A plan can state a destination and count steps, but has **no concept of distance travelled.**

Three things move a plan today, and all three measure *activity*, not *achievement*:

| Mover | Weight | Measures |
|---|---|---|
| Task completion | `masterplan_progress` × 0.6 | how many tasks ticked |
| Schedule | `masterplan_progress` × 0.4 | whether time is passing on plan |
| WCU | `total_wcu` → phase gate | volume of completed work |

Complete every task, dead on schedule, having earned nothing and shipped nothing, and the plan
reads as perfect progress.

**The structural cause.** The anchor declares a target with no counterpart:

```python
anchor_date      = Column(DateTime)   # target date
goal_value       = Column(Float)      # e.g. 100000.0
goal_unit        = Column(String)     # e.g. "USD", "books", "tasks"
goal_description = Column(Text)
```

There is **no `goal_current`**. `goal_value` is write-only — set by `PUT /masterplans/{id}/anchor`,
echoed back on read, never compared to anything. Verified: the only references outside the column
definition are assignment and echo.

The typed alternative (`gross_revenue`, `books_published`, `active_playbooks`, `platform_live`,
`studio_ready`) has the mirror-image flaw: the fields exist and **nothing ever writes them**, which
is what makes `evaluate_phase` permanently unsatisfiable.

---

## 2. Design

**Resolve on read. No new column, no write path, no migration.**

```
masterplan_progress
  └─ goal_attainment_resolver          (apps/analytics/services/integration/)
       └─ unit registry: goal_unit → domain
            └─ sys.v1.<domain>.get_goal_metric   (syscall, capability-gated)
```

Three properties this buys:

- **No cross-app imports.** Resolution goes over syscalls, mirroring `dependency_adapter`. No
  `APP_DEPENDS_ON` changes, no import-boundary risk.
- **No staleness.** Nothing to keep in sync; attainment is computed when read.
- **Generic.** Works for any unit any user declares. `books_published` becomes
  `goal_unit = "books"` — no column per goal type, which is the property that makes it usable by
  someone other than the owner.

### Placement

`apps/analytics/services/integration/goal_attainment.py`, beside `dependency_adapter.py` — the
consumer is `masterplan_progress` (analytics-owned) and the existing adapter is the established
precedent for analytics reaching other domains by syscall.

---

## 3. The syscall contract

Existing `sys.v1.<domain>.get_performance_signals` syscalls are **the wrong shape** — they return
the top-N advisory signal list (`{type, reason, engagement_score, content}`), not a measurable
quantity. Confirmed in `social_performance_service.get_social_performance_signals`, which returns
`summary["signals"]`, discarding the `overview` counters.

A new, uniform contract is required.

```
name:       sys.v1.<domain>.get_goal_metric
capability: <domain>.read

request:  {"user_id": str, "unit": str, "masterplan_id": int | None}
response: {"supported": bool, "value": float, "unit": str, "as_of": iso8601 | None}
```

Rules:

- `supported: false` when the domain cannot answer that unit. **Never raise** — an unsupported
  unit is a normal answer, not an error.
- `value` is **cumulative-to-date**, matching the semantics of `goal_value` as a target.
- `masterplan_id` is passed so a domain *may* scope to a plan (tasks does); domains that cannot
  scope ignore it and answer user-wide.

---

## 4. Unit registry — what is resolvable

| `goal_unit` (+ aliases) | Domain | Source | Status |
|---|---|---|---|
| `tasks` | tasks | completed tasks for the plan | ✅ **Phase 0** — `sys.v1.task.list_for_masterplan` |
| `USD`, `revenue`, `$` | freelance | delivered-order prices, summed live | ✅ **Phase 1** — `sys.v1.freelance.get_goal_metric` |
| `impressions`, `clicks`, `posts` | social | `summarize_social_performance()["overview"]` | ✅ **Phase 1** — `sys.v1.social.get_goal_metric` |
| `playbooks` | rippletrace | `PlaybookDB` count | ✅ **shipped** (#178) — `sys.v1.rippletrace.get_goal_metric`, wired as `_rippletrace_metric`. Reports `scope: "global"`; the table is empty until rippletrace has ingested content |
| `books` | authorship | — | ❌ **no publication concept exists**; the domain has one route (`/reclaim`). The only unit family still unresolvable |

**Scope decisions made in Phase 1:**

- **Freelance answers user-wide, not plan-scoped**, even though `FreelanceOrder` carries
  `masterplan_id`. Orders are rarely plan-linked in practice, so plan-scoping would report 0 for
  almost everyone. The response carries `scope` explicitly rather than leaving it implicit.
- **Revenue is summed live from delivered orders**, not read from `revenue_metrics` — that table
  has no `user_id` (it is a global snapshot) and so cannot answer a per-user goal.
- **A degraded domain reports `supported: False`, never 0.** Social reads Mongo and degrades; a
  degraded read must not be scored as "achieved nothing".

**Remaining:** `playbooks` and `books` have no signal to read. The registry slots exist; the
underlying data does not.

`studio_ready` has no plausible domain feeder and should be dropped rather than mapped.

---

## 4b. ★ WCU — the unit that exists, is computed, and cannot be pointed at anything

Added 2026-09-07 from an owner observation about the qualitative half of a plan:

> *"You can explain things, but you still need something to actually measure/work against."*

That is the whole problem with `structure_json["success_criteria"]`. Genesis produced five of
them for the live plan — *"Establishment of a widely adopted ethical AI framework"* and similar.
They are true statements of what success means and they have **no unit and no number**, so seeded
into `goals` they would be permanently `unresolved`. The registry above cannot help: there is no
`goal_unit` for "a framework became widely adopted".

**This repo already built the answer, and it is WCU.** `MasterPlan.total_wcu` — Work Complexity
Units — is the accumulated complexity of a plan's *completed* tasks, and it is the closest thing
here to a universal unit of work done. Measured live 2026-09-07: `total_wcu = 2`, from

```
Task 17 "Fix Nodus Issues"   duration 1 x complexity 1 x difficulty 1 = 1
Task 18 "Close A.I.N.D.Y. PR"  no duration -> default 1.0 x 1 x 1     = 1
```

So the machinery works. Four things stop it being usable as the proxy the owner is describing,
and they are worth separating because only one of them is hard.

### The three easy ones

1. **`wcu` is not in the unit registry.** `supported_units()` returns
   `clicks, impressions, playbooks, posts, tasks, usd`. A goal cannot be declared in the one unit
   this repo invented for the purpose. Adding a resolver is small — `total_wcu` is a column on the
   plan the resolver already receives.

2. **Two of the formula's three terms are inert.** WCU is
   `effort_hours x task_complexity x task_difficulty`, and **every task on the live plan has
   `task_complexity = 1` and `task_difficulty = 1`** — the column defaults. Nothing in the create
   path or the UI sets either. So WCU currently reduces to *estimated hours*, which `Task.duration`
   already reports directly. The "complexity" in Work Complexity Units is not being measured.

3. **`wcu_target = 3000` is a stale default**, from the same books/studio/playbooks product shape
   as the rest of `evaluate_phase`'s thresholds (see `STRATEGY_LAYER_SPEC` §3). At ~1 WCU per
   completed task that is roughly 3,000 tasks to advance a phase.

### ★ The hard one: WCU is plan-scoped, so it cannot answer a goal

`total_wcu` lives on `master_plans`. There is no way to express *"3,000 WCU toward the ethical AI
framework"*, because **WCU has no idea which goal a task served** — a task carries
`masterplan_id` and nothing else. The chain from work to purpose does not exist.

So adding `wcu` to the registry would make every goal on a plan report the *same* number: the
plan's total. With one goal that is a fine proxy. With five it is actively misleading — five
goals all reading 40% because the plan is 40% worked.

**Attribution is the missing piece, and it is not this spec's to solve.** It is precisely what
`STRATEGY_LAYER_SPEC` exists for: `task -> strategy -> objective`. With that chain, WCU rolls up
per objective and a qualitative criterion becomes measurable *as the work done against it* — which
is the honest reading of a goal like "establish a framework", since the framework is not a number
but the work toward it is.

Without the chain, WCU can measure **that** you worked. It can never measure that you worked
**on this**.

### What follows from that

- **Seeding `goals` from `success_criteria` should wait.** Five permanently-unresolved goals in a
  table with no UI (verified 2026-09-07: nothing in `client/src` calls the goals API) is the
  dead-surface shape this repo keeps producing.
- **Adding `wcu` to the registry is defensible now, on its own terms**, provided the response
  reports `scope: "plan"` the way freelance already reports `scope: "user"`. An honest plan-wide
  number is useful; an implied per-goal one is not.
- **Fixing the inert terms is a separate and smaller question** than either: nothing collects
  complexity or difficulty, so the first move is deciding whether a human supplies them, an agent
  estimates them, or the formula drops them and admits it measures hours.

---

## 5. Formula change

Current (`infinity_service.calculate_masterplan_progress`):

```python
score = (completion_pct * 100 * 0.6) + (schedule_score * 0.4)
```

Proposed, **only when a goal is declared and resolvable**:

```python
attainment_pct = min(1.0, resolved_value / goal_value)      # goal_value > 0
score = (attainment_pct * 100 * 0.40)
      + (completion_pct  * 100 * 0.35)
      + (schedule_score        * 0.25)
```

Attainment carries the largest single weight — the point is that achievement should outrank
task-ticking. The split is a starting value, not a derived one; see §7.

**Fallback is mandatory and total.** Any of — no active plan · no `goal_value`/`goal_unit` ·
`goal_value <= 0` · unit unsupported · syscall failure or timeout — falls back to the **current
formula unchanged**. Scoring must never regress or throw because a domain is degraded. The
existing `except → return 50.0, 0` guard stays as the outer backstop.

**Clamp at 100%.** Exceeding a goal must not inflate the KPI past its ceiling; overachievement is
visible in the projection payload, not the score.

---

## 6. Rollout

Matches how this repo has shipped every other scoring change (three-axis shadow → advisory →
default):

1. ✅ **Phase 0 — resolver + registry.** `goal_attainment.py`, `tasks` unit only. Not wired to
   scoring. Exposed read-only on the projection payload so it is inspectable. Shipped #173.
2. ✅ **Phase 1 — new syscalls.** `freelance` and `social` `get_goal_metric`, plus `rippletrace`
   (#178). Still unwired. Four of the five unit families now resolve.
3. ✅ **Phase 2 — shadow. Shipped 2026-09-11, and not in the form this section expected.**
   The blend's attainment term is **attribution-based**, not a declared goal: hours completed
   against each objective through `task → strategy → objective` (§4b's missing chain, built
   by `STRATEGY_LAYER_SPEC` §5b), hours-weighted to a plan figure. Masterplan answers
   `sys.v1.masterplan.get_objective_attainment`; analytics reads it by syscall, blends it with
   the §5 weights, and records `live_score` next to `shadow_score` in
   `goal_attainment_shadow_records` on every score event. **`AINDY_MASTERPLAN_GOAL_ATTAINMENT_
   SHADOW` defaults ON** — recording changes no score, and a shadow nobody records cannot end a
   soak. An objective with no planned work is unmeasured (`NULL`), not 0%, and a plan with
   nothing measured records a shadow equal to live — the mandatory fallback, by construction.
   Report: `GET /apps/analytics/goal-attainment/shadow` (`mean_divergence` is the signal).
   Owner's call: *"yes, as a shadow first."*
4. **Phase 3 — flip.** The blend becomes live behind `AINDY_MASTERPLAN_GOAL_ATTAINMENT`,
   default off, after a real soak. The code path exists (same resolver, same blend); the flag
   is the decision, and the decision waits on the ledger.

Phases 0–1 were safe to merge immediately because nothing observes them — and nothing does
today, which is why the resolvers exist but no plan is measured by them yet.

**Superseded in part.** `MASTERPLAN_DOMAIN_ENGINE_SPEC.md` (the structural path, chosen
2026-08-05) is where these resolvers get consumed: they become the `current_value` writers for
plan-scoped domains. Phases 2–3 below describe blending attainment into the *existing* six-column
gate; the Domain Engine replaces that gate instead. Treat this document as the **unit-resolution
contract** — which is live and still correct — rather than as the remaining rollout plan.

---

## 7. Weight calibration — open question

`0.40 / 0.35 / 0.25` is asserted, not derived. Two things to note before treating it as settled:

- The learned-weights system (`adapt_kpi_weights`) tunes weights **between** the five KPIs, not
  **inside** one. This split is a fixed constant unless that changes.
- A user whose goal is `tasks` gets attainment and completion measuring nearly the same thing,
  double-counting to 0.75. Worth either detecting that overlap or documenting it.

Recommend shipping the shadow phase and comparing distributions before committing.

---

## 8. Test plan

**Unit — resolver**
- each registered unit resolves to the right domain; aliases normalize (`USD`/`usd`/`$`)
- unsupported unit → `supported: false`, no raise
- syscall raises → resolver returns unresolved, never propagates
- `goal_value = 0` / negative / null → unresolved

**Unit — formula**
- no goal declared → byte-identical to today's score (regression lock)
- attainment 0 % / 50 % / 100 % / 150 % → expected score, clamped at 100
- unresolvable unit → identical to today's score
- no active plan → `(50.0, 0)` unchanged

**Integration**
- plan with `goal_unit="tasks"`, `goal_value=10`, 4 completed → attainment 40 %, score reflects it
- freelance delivered orders → `USD` attainment moves the score
- domain degraded mid-run → score still returned, fallback path taken

**Contract**
- every registered `get_goal_metric` syscall satisfies the response schema
- capability enforcement holds (`freelance.read` etc.)

---

## 9. What this does not do

- Does **not** touch `evaluate_phase`. The unsatisfiable gate is a separate decision
  (redesign brief §5); this spec deliberately leaves it alone.
- Does **not** write the five typed progress columns. They stay unwritten and unread.
- Does **not** implement the hub model — domains still feed Infinity directly. This makes the
  plan a *better-fed spoke*, per the owner's call.
- Does **not** give rippletrace or authorship a real feed. It opens the registry slot; the
  underlying signals still do not exist.
- Does **not** make a qualitative criterion measurable. §4b is the analysis of why: the unit
  exists (WCU) and the attribution does not, and attribution belongs to `STRATEGY_LAYER_SPEC`.

---

## 10. Effort

| Phase | Work | Size |
|---|---|---|
| 0 | resolver, registry, `tasks` unit, projection exposure, unit tests | small |
| 1 | 2 syscalls (`freelance`, `social`) + contract tests | small |
| 2 | shadow record + flag + comparison read | small |
| 3 | flip + soak | trivial code, real observation time |

Small throughout, because **nothing new is computed** — every underlying signal already exists and
is already reachable by syscall. The work is connection, not construction.
