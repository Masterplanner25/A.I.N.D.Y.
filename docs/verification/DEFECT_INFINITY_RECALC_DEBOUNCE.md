---
title: "Defect — the Infinity recalculation debounce cannot fire, and its lease does not exclude"
last_verified: "2026-08-19"
api_version: "1.0"
status: current
owner: "app-team"
---

# Defect — the Infinity recalculation debounce cannot fire, and its lease does not exclude

**Found 2026-08-19** while answering a narrower question from
[`DEFECT_GENESIS_MESSAGE_LATENCY.md`](./DEFECT_GENESIS_MESSAGE_LATENCY.md): *where is a
turn-level score supposed to land?* The answer turned out to be "it already lands correctly"
(§4 there). This is what was found on the way.

**Severity: low today, high at real usage.** Both guards around `execute()` are keyed on a field
that the previous run overwrites, so in ordinary alternating traffic neither one engages. Nothing
is visibly wrong right now because the product has one active user. **This is a defect that gets
worse precisely as the "just use it" remedy in `SOAK_AUDIT_2026-08-15.md` succeeds.**

**Static analysis only.** Everything below is read from source. None of it has been observed
against a running stack — the host could not hold the stack up long enough on the day it was
found (see §5). Treat the race in §2 as grounded but unconfirmed.

---

## 1. The debounce cannot fire in alternating traffic

`apps/analytics/services/orchestration/infinity_orchestrator.py`

```python
_ANALYTICS_DUPLICATE_DEBOUNCE_SECONDS = 1          # line 21

def _was_recently_executed(*, db, user_id, trigger_event, window_seconds):   # line 88
    row = db.query(UserScore).filter(UserScore.user_id == normalized_user_id).first()
    if row is None:
        return False
    if (row.trigger_event or "") != trigger_event:
        return False                                # <-- mismatch means "not recent"
    ...
    return updated_at >= (_utcnow() - timedelta(seconds=window_seconds))
```

Two independent reasons it does not work:

**a. The window is one second.** That is a double-submit guard, not a rate limit. Any two events
more than a second apart — which is every real interaction — both recalculate.

**b. It is keyed on a field that holds only the *last* trigger.** `user_scores.user_id` is
`unique=True` (`apps/analytics/user_score.py:48`), so there is exactly one row per user and one
`trigger_event` column on it. The sequence in normal operation is:

| Event | `row.trigger_event` before | Match? | Result |
|---|---|---|---|
| scheduled run | `genesis_message` | no | recalculates, stamps `scheduled` |
| chat turn | `scheduled` | no | recalculates, stamps `genesis_message` |
| scheduled run | `genesis_message` | no | recalculates, stamps `scheduled` |

**Alternating triggers defeat the debounce permanently.** It can only ever fire for two
same-trigger events inside one second — the narrowest case, and the one least worth guarding.

The check is not merely mistuned. Raising `_ANALYTICS_DUPLICATE_DEBOUNCE_SECONDS` alone would not
fix it, because condition (b) short-circuits before the window is consulted.

---

## 2. The lease is per-trigger, so it does not mutually exclude

```python
lease_name = f"analytics.infinity:{user_id}:{trigger_event}"     # line 207
```

The lease name includes the trigger. A `scheduled` recalculation and a `genesis_message`
recalculation **for the same user** therefore acquire *different* leases and are free to run
concurrently — both computing all five KPIs and both upserting the same single `user_scores` row.

The lease correctly prevents two runs of the *same* trigger from overlapping. It was, as far as the
name suggests, intended to prevent duplicate work per user; keyed this way it prevents duplicate
work per user *per trigger kind*, which is a weaker guarantee than the surrounding code reads as
providing.

**Corroborating signal, not proof:** `infinity_service.py` carries a `_SCORE_WRITE_RETRY_LIMIT`
retry loop around the `user_scores` write. Retry logic on that write is what you would build after
observing contention on it. That is suggestive, not evidence — it may equally be ordinary
defensiveness.

**Confirm before fixing.** Two concurrent same-user recalculations writing one row is a
last-writer-wins situation over `master_score`, and the losing computation is discarded work. The
scenario is reachable from the code; it has not been reproduced.

---

## 3. `genesis_message` was never admitted to the trigger vocabulary

`apps/analytics/services/scoring/infinity_service.py`, docstring of the persist function:

```
trigger_event: "task_completion" | "session_ended" | "arm_analysis" | "scheduled" | "manual"
```

`apps/automation/flows/flow_definitions.py:254` passes `"genesis_message"`. The column is a plain
`String`, so it stores without complaint and every read path works.

**This is a documentation defect with a design signal inside it.** Somebody decided a conversational
turn is a scoring event — that is what passing a distinct trigger means — and then did not finish
the decision. The consequence is that the vocabulary a reader consults to learn "what kinds of
things move the score" omits one of the kinds that does.

The right resolution is to add it to the documented set, not to remove it from the call site. See
§4 of the latency defect for why the turn-as-scoring-event reading is the correct one.

---

## 4. Why this is worth fixing before there are users, not after

Every one of these is invisible at current usage and none of them is invisible at real usage:

- **Debounce**: one user sending occasional messages produces few enough recalculations that a
  broken throttle costs nothing. A user in an actual Genesis conversation produces one full 5-KPI
  recalculation **per turn**, and the throttle that should absorb that cannot engage.
- **Lease**: two concurrent recalculations require two triggers landing close together, which
  needs traffic.
- **Volume**: `score_history` is append-only by design and correctly so (§4 of the latency defect)
  — but "append one row per chat turn" and "append one row per completed task" are very different
  growth rates, and only the second was in the documented vocabulary when the table was designed.

`SOAK_AUDIT_2026-08-15.md` concluded every measurement gate is **usage-blocked**. These three
defects are the shape of thing that converts "finally getting usage" into "the recalculation path
is now the dominant write load."

---

## 5. What was not done, and why

Nothing here was verified against a running stack. On the day it was found the host was
committing 26.7 GB against 7.7 GB of physical memory and taking **56,000 hard page faults per
second**; the API container sat `running` with zero restarts and produced no log output for five
minutes at a stretch. That environment cannot distinguish an application stall from a starved one
— which is itself recorded in §8.1 of the latency defect as a negative result.

**Before fixing any of this, verify on a host that is not thrashing:**

1. That two alternating-trigger recalculations for one user do both run (§1).
2. Whether they can overlap, and what happens to `user_scores` when they do (§2).
3. What the actual per-turn cost of `calculate_infinity_score` is, which decides whether the fix is
   "debounce properly" or "do not recalculate per turn at all".

---

## 6. Related — the async path this interacts with

`apps/analytics/bootstrap.py` registers **no** `register_async_job`. It registers
`register_job("analytics.infinity_execute", ...)` (line 116), which is a synchronous callable
lookup, plus a scheduled recalculation (`trigger_event="scheduled"`, line 310).

That matters here because §8.4 of the latency defect proposes adding an async job for the
recalculation. **Doing so removes the recalculation from the request path but does not change how
often it runs** — the debounce in §1 is what should govern frequency, and it cannot fire. Fix them
together or the async queue simply inherits the unthrottled rate.
