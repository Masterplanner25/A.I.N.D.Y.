---
title: "Starting position — accounting for what happened before the system"
last_verified: "2026-08-16"
api_version: "1.0"
status: current
owner: "app-team"
---

# Starting position — accounting for what happened before the system

**Status:** spec, not started. Written 2026-08-16.

> **Implementation is deliberately gated on
> [`DEFECT_GENESIS_MESSAGE_LATENCY.md`](../verification/DEFECT_GENESIS_MESSAGE_LATENCY.md) / FR-15.** The owner's
> real MasterPlan is blocked on that fix, and this spec exists because importing that plan raises
> the question. Building the baseline before there is a plan to attach it to would repeat the
> pattern the soak audit called out: more machinery around a core with nothing in it.

---

## 1. The question

> *"How do we account for what happened before they entered the system, if need be?"*

Every counter in this product starts at zero the day the plan is locked. For a new user that is
correct. For someone who has spent years building the thing being measured, **zero is a false
statement** — the same null-vs-zero defect the soak audit identified in `realized_revenue`
(`SOAK_AUDIT_2026-08-15.md` §2a), arriving from a different direction.

The naive fix — backfill history — is wrong, and differently wrong per axis.

---

## 2. "Before" cuts differently for each axis

This is the load-bearing section. There is no single answer, and treating it as one is how
calibration gets quietly poisoned.

| Axis | Can prior state be honestly recorded? | Why |
|---|---|---|
| **Worth** | **Yes.** | `strategic` / `intrinsic` declarations are assertions about value. The value of work already done is a fact assertable today. Nothing about it requires hindsight to be dishonest. |
| **Capacity** (runway) | **Not applicable.** | A present-tense stock. History is irrelevant — see `CAPACITY_AND_RUNWAY_SPEC.md`. |
| **Volume** | **Partly, as a declared baseline.** | Throughput is a count. A count of completed prior work can be asserted honestly in aggregate; inventing individual task rows with fabricated timestamps and effort cannot. |
| **Trajectory** | **NO. Never backfill.** | Trajectory is estimate-vs-actual. You cannot retro-fit an estimate you already know the answer to. Every backfilled pair is contaminated by hindsight, and hindsight-free estimation is the entire thing being measured. |

**The Trajectory row is a hard constraint, not a preference.** `SELF_TRUST_CALIBRATION_SPEC.md`
exists to measure whether your predictions match reality. A prediction authored after the outcome
is known is not a prediction. Admitting even a few would make the calibration score
*confidently wrong* — the failure mode the soak audit found in the learned calibrator, reproduced
deliberately.

So the answer is **not "backfill history."** It is **"declare a starting position"**: an as-of
baseline, asserted once, permanently marked as declared rather than measured.

---

## 3. The mechanism already exists and is already wired to something important

This is not a new subsystem. `MasterPlan` already carries six cumulative progress counters, and
`evaluate_phase` already gates phase advancement on them (`projection_service.py:75`):

| Counter | Target field | Default |
|---|---|---|
| `total_wcu` | `wcu_target` (3000) | 0 |
| `gross_revenue` | `revenue_target` (100000) | 0 |
| `books_published` | `books_required` (3) | 0 |
| `platform_live` | `platform_required` (True) | False |
| `studio_ready` | `studio_required` (True) | False |
| `active_playbooks` | `playbooks_required` (2) | 0 |

```python
thresholds_met = (
    _requirement_met(plan.total_wcu, plan.wcu_target)
    and _requirement_met(plan.gross_revenue, plan.revenue_target)
    and ... )
if thresholds_met:
    return 2
```

**These six fields are precisely "what happened before you entered the system."** And two of them
are booleans that are *already true in reality*: the owner has built the platform. `platform_live`
is `False` because nothing ever set it, not because the platform does not exist.

So the surface to seed is identified, exists, and already drives behaviour. What is missing is any
honest way to set it.

---

## 4. Design

### 4.1 Declared baseline, never merged into measured

A new app-owned table, `plan_baseline_declarations`, attached to a `masterplan_id`:

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `masterplan_id` | FK, indexed — a baseline belongs to a plan, not a user |
| `metric` | one of the six counter names, validated against a constant set |
| `declared_value` | float / bool-as-float |
| `as_of` | the date the claim describes |
| `basis` | free text — *"3 books published 2023–2025"*. Required, not optional |
| `created_at` | append-only |

**The baseline is never written into `total_wcu` et al.** Those stay measured-only. Reads compose:

```
displayed_total = measured_total + baseline_total
```

Persisting the sum would destroy the distinction within one release, and the distinction is the
whole point. This mirrors the runway design: `source` is preserved, not collapsed.

### 4.2 Provenance is surfaced, always

Anywhere a composed total appears it must be decomposable — *"3,240 WCU (1,900 declared prior,
1,340 measured)."* A baseline the user cannot see is a baseline they will forget they asserted, and
the number silently becomes fiction.

### 4.3 Phase advancement — the dangerous part

`evaluate_phase` returns phase 2 the moment all six thresholds are met. If baselines feed it
directly, **a user advances a phase by typing numbers into a form.**

Options, in preference order:

1. **Baselines count toward thresholds, but phase advancement driven by a baseline is flagged**
   and requires explicit confirmation. Honest prior work should count — refusing it is the same
   error as reporting `0.00` for a real business — but it should never be silent.
2. **Baselines are display-only** and never reach `evaluate_phase`. Safe, but re-creates the
   original problem: the phase model still believes you have done nothing.
3. **Baselines shift the target instead of the progress** — you started partway, so the remaining
   distance is shorter. Conceptually cleanest, most invasive.

**Recommend 1.** It is honest, it is visible, and it keeps one code path.

### 4.4 What a baseline is not

It is not a task, not an order, not a memory node. It creates **no** rows in `tasks`,
`freelance_orders`, or `memory_nodes`. Nothing downstream may treat a baseline as an event —
particularly not the learning loops (`#122` / `#126` / `#127`), which read realized outcomes and
would learn from fiction.

---

## 5. Interaction with `ambition_score` and the phase model

`ambition_score` is read by the Genesis LLM from the plan text and drives `determine_posture`. A
plan authored by someone with a large starting position is a *different plan* from the same words
authored by a beginner — "build a platform" is ambitious once and maintenance thereafter.

Not resolved here, but flagged: **the baseline should be visible to Genesis at synthesis time**, or
ambition will be scored against a blank slate. The import path (`POST /apps/genesis/import`,
already wired at `Genesis.jsx:119`) is the natural place — a plan the owner already wrote *contains*
its own history, and that is the most honest source of a baseline there will ever be.

That suggests a sequencing worth taking seriously: **import the real plan first, and let the
baseline be extracted from it and confirmed**, rather than typed into a form afterwards.

---

## 6. Rollout

**Gated on the latency fix. Nothing here starts before FR-15 and the app-side
`execute_infinity` change are in.**

1. **Phase 0 — the two booleans.** `platform_live` and `studio_ready` are already true in reality.
   Setting them is a one-row baseline each and needs almost none of the machinery below. Cheapest
   possible proof the idea is right.
2. **Phase 1 — model + declare + compose on read.** Table, migration, service, routes, provenance
   in the read path. Display-only; `evaluate_phase` untouched.
3. **Phase 2 — feed thresholds, flagged.** §4.3 option 1, with explicit confirmation on any
   baseline-driven phase advance.
4. **Phase 3 — extraction at import.** Genesis proposes a baseline from the imported plan text;
   the user confirms or edits each line. Never auto-accepted.

Phase 0 is worth doing on its own even if the rest is deferred.

---

## 7. What this does not do

- **Does not backfill Trajectory or any calibration pair.** §2. This is a hard line.
- Does not create tasks, orders, or memory nodes.
- Does not merge declared into measured, ever.
- Does not let a baseline silently advance a phase.
- Does not attempt to reconstruct *when* prior work happened. A baseline is a single `as_of`
  assertion, not a synthetic history, and it cannot produce a trend.

---

## 8. Open questions

- **Can a baseline be revised?** Append-only history says yes, with the supersession visible. But
  a baseline that moves whenever the target looks far away is self-deception with a database
  behind it.
- **Does a baseline expire?** Prior work does not stop having happened, but its relevance decays —
  a platform built five years ago is not the platform the plan needs today.
- **Who validates `basis`?** Nobody, and that is the honest answer: this is a self-report. The
  defence is visibility (§4.2), not verification. Worth stating plainly in the UI so it is
  understood as a declaration.
- **Should the six counters even be the model?** They encode one specific plan shape — books,
  platform, studio, playbooks. The Domain Engine
  (`MASTERPLAN_DOMAIN_ENGINE_SPEC.md`) proposes user-defined typed domains, which would make the
  baseline generic instead of hardcoded to these six. **If the Domain Engine lands first, this
  spec should be rewritten against domains rather than counters** — that is the better end state,
  and this spec should not entrench the current shape.
