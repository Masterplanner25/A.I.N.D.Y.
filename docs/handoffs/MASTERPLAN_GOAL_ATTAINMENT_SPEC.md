# MasterPlan Goal Attainment — Implementation Spec

**Status:** spec, not started. Written 2026-08-01.
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
| `playbooks` | rippletrace | `PlaybookDB` count | ❌ needs syscall — **and the table is empty** |
| `books` | authorship | — | ❌ **no publication concept exists**; the domain has one route (`/reclaim`) |

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

1. **Phase 0 — resolver + registry.** `goal_attainment.py`, `tasks` unit only. Not wired to
   scoring. Exposed read-only on the projection payload so it is inspectable.
2. **Phase 1 — new syscalls.** `freelance` and `social` `get_goal_metric`. Still unwired.
3. **Phase 2 — shadow.** Compute the blended score alongside the live one, record both, change
   nothing. Flag `AINDY_MASTERPLAN_GOAL_ATTAINMENT_SHADOW`.
4. **Phase 3 — flip.** Blend becomes live behind
   `AINDY_MASTERPLAN_GOAL_ATTAINMENT`, default off, after a real soak.

Phases 0–1 are safe to merge immediately; nothing observes them.

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
