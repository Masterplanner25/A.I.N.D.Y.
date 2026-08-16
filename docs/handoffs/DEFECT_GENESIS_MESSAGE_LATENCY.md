---
title: "Defect — Genesis message latency is unbounded, and it can take the API down"
last_verified: "2026-08-16"
api_version: "1.0"
status: current
owner: "app-team"
---

# Defect — Genesis message latency is unbounded, and it can take the API down

**Found 2026-08-16** while answering a different question: *does a Genesis session actually lock?*
It does (§5). Getting there surfaced this.

**Severity: high.** A single user, sending a normal sequence of chat messages, made the whole API
unresponsive for **13 minutes** — `/health` included — with no error, no restart, and no way to
tell from the UI that anything was wrong other than a request that never returned.

---

## 1. Reproduction

Reproduced on the live stack, `aindy-runtime==2.1.0`, single user, no other traffic.

Two concurrent messages on one session, then three sequential with no pause:

| Request | Wall time |
|---|---|
| concurrent #1 | 5.4s |
| concurrent #2 | 18.2s |
| sequential #3 | 48.8s |
| sequential #4 | 22.3s |
| sequential #5 | **184.1s** |

**Latency is not merely high, it is unbounded and non-monotonic** — 5s to 184s across five
identical-shaped calls. The first episode (two back-to-back messages) exceeded a 240s client
timeout and left the API pegged at **274% CPU for 13 minutes** with `/health` timing out. A
manual `docker restart` was required. The second episode recovered on its own.

**One negative result, recorded so nobody re-runs it:** two messages back-to-back on a *fresh,
idle* stack completed in 23.5s and 12.5s. The defect needs some accumulated load or session depth
to appear, which is why it will not show up in a quick manual test.

---

## 2. Where the time goes — it is not the LLM

Event timeline for the 184s request (`trace 6c90c64b`, `system_events`):

```
genesis.message.started   06:00:39.495
external.call.started     06:00:39.834
external.call.completed   06:00:40.181   ← LLM call 1   0.3s
external.call.completed   06:00:40.680   ← LLM call 2   0.4s
external.call.completed   06:00:41.211   ← LLM call 3   0.3s
external.call.completed   06:00:43.180   ← LLM call 4   1.8s
execution.started         06:03:40.561   ← gap of 177.4 SECONDS, zero events
flow.node.started/…       06:03:40.6-41.4  ← the entire flow: ~0.9s
execution.completed       06:03:41.451
memory.write              06:03:41.585
external.call.completed   06:03:43.141   ← 1.4s
embedding.started         06:04:09.472   ← further 26.3s gap
embedding.completed       06:04:13.839   ← 4.4s
```

**All four LLM calls total 3.7 seconds. The flow itself runs in about one second.** The 184
seconds is almost entirely a **177-second window in which nothing is recorded at all**, between
the model returning and the execution pipeline starting — plus a second 26s stall before
embedding.

So this is not slow AI and not slow business logic. **It is waiting.**

---

## 3. Mechanism — evidenced, and partly hypothesis

**What is certain:**

- The dead window sits *before* `execution.started`, so the request is blocked getting **into**
  the execution pipeline, not running inside it.
- There are two distinct stall points: pre-execution (177s) and pre-embedding (26s).
- During the severe episode the process burned ~2.7 cores while emitting almost no log output and
  only ~3 `system_events` per 10 seconds — busy, but not doing recordable work.
- APScheduler logged, continuously:
  `Execution of job "Scheduler heartbeat tick (trigger: interval[0:00:01])" skipped: maximum
  number of running instances reached (1)` — a 1-second heartbeat unable to complete within its
  own interval.

**What is inferred and should be confirmed before anyone "fixes" it:** something on this path
serialises through a single slot, so requests and background work queue behind one another and
the queue grows faster than it drains. The heartbeat starvation is consistent with that, but it
is a *symptom* of a saturated executor and does not by itself prove the mechanism.

**Do not attribute this to the 2.1.0 upgrade without checking.** The heartbeat warnings begin at
03:44:53, during an unrelated image build on a loaded machine, ~1.5h before any Genesis traffic.
That timing is coincidental to the upgrade, and this repo has a documented history of
misattributing load-dependent failures (`CLAUDE.md`, the nodus 45s-limit note).

---

## 4. The app-side amplifier

Whatever the underlying serialisation is, the app makes it far worse:

```python
@register_node("genesis_message_orchestrate")        # apps/automation/flows/flow_definitions.py:254
def genesis_message_orchestrate(state, context):
    orchestration = _syscall_data(
        "sys.v1.analytics.execute_infinity",
        {"user_id": ..., "trigger_event": "genesis_message"}, ...)
```

**Every chat message triggers a full Infinity recalculation, synchronously, inside the request.**
A conversational turn is not a scoring event. Nothing in the UI needs the recalculated score
before the reply can be rendered — the reply is already in `state["genesis_response"]`.

This is the cheapest available fix and it is app-owned: **make the recalculation asynchronous, or
drop it from the message path entirely and recalculate on lock.** `register_async_job` is already
used by this domain (`apps/masterplan/bootstrap.py:127`).

---

## 5. What does work — recorded so it is not re-litigated

The lock path itself is healthy. Full walk on a throwaway account:

| Step | Result |
|---|---|
| `POST /apps/genesis/session` | 200 |
| `POST /apps/genesis/message` | 200 (see §1 for latency) |
| `POST /apps/genesis/synthesize` | 200, **8.7s** |
| `GET /apps/genesis/draft/{id}` | 200, 1.0s |
| **`POST /apps/genesis/lock`** | **200, 1.3s** |

Result: `master_plans` row `id=9`, `status=locked`, `posture=Accelerated`, `version_label=V1`,
`phase=1`. **The spine can exist.** The two pre-existing sessions (2026-08-01, 2026-08-06) that
never locked were not blocked by a lock defect.

Two related observations:

- **`synthesis_ready` is set by the LLM, not by a rule.** `genesis_ai.py` instructs the model to
  set it once `vision_summary`, `time_horizon` and `mechanism_summary` are all present. Session 3
  had all three populated after turn 1 and the flag was still `false` — the model chose to ask
  about assets first. So "the required fields exist" and "the model says ready" are different
  conditions, and only the second gates synthesis. A user one confirming sentence short of ready
  gets a `422` and no indication of what is missing.
- **Error handling on this path is good.** `synthesize` against a not-ready session returns a
  precise `422 synthesis_not_ready`, not an opaque 500 — the pre-pipeline-raise discipline is
  holding here.

---

## 6. Remedies, cheapest first

1. **Take `execute_infinity` off the message path** (app-owned, small). Async job or move to lock.
   Removes the amplifier regardless of the root cause.
2. **Put a timeout on the message request** so a stall fails loudly instead of hanging a client
   for four minutes.
3. **Establish what serialises** — the 177s pre-execution window is the actual bug and neither
   remedy above fixes it. Filed as **FR-15**.
4. **Bound the embedding stall** — the second 26s gap is smaller but the same shape.

---

## 7. Why this matters more than it looks

The soak audit (`SOAK_AUDIT_2026-08-15.md`) concluded that every measurement gate in the system is
**usage-blocked**: the data is degenerate because nobody uses the product enough to vary it.

This defect is one concrete reason why. Genesis is the front door to the MasterPlan, the MasterPlan
is the spine everything else scores, and **conversing with it is a coin-flip between 5 seconds and
"the app is broken."** Two of the owner's own sessions sit unlocked since 2026-08-01 and 2026-08-06.

**Fixing this is a prerequisite for the "just use it" remedy** the audit recommends. You cannot ask
someone to use a product daily when its primary authoring surface intermittently hangs.

**It is also an explicit gate on other work.** The owner's real MasterPlan is blocked on this fix —
`POST /apps/genesis/import` (wired at `Genesis.jsx:119`) is the intended path for the four existing
plan documents, and a large import is precisely the input most likely to hit the bad tail.
[`STARTING_POSITION_SPEC.md`](./STARTING_POSITION_SPEC.md) is gated on the same fix for the same
reason.
