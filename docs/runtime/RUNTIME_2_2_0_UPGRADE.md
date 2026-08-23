---
title: "Upgrading to aindy-runtime 2.2.0"
last_verified: "2026-08-16"
api_version: "1.0"
status: current
owner: "platform-team"
---

# Upgrading to `aindy-runtime==2.2.0`

**Released 2026-08-16. Minor — arrives passively like 2.1.0, but unlike 2.1.0 it *removes*
something.** Floor moved to `>=2.2.0,<3.0` so the version we run stays a choice.

Every claim below was checked against this repo on 2026-08-16.

---

## TL;DR

| | Action |
|---|---|
| Version pin | **Moved** to `>=2.2.0,<3.0` |
| `GUEST-CONFINE-1` — 31 builtins now denied to Nodus guests | **None.** Exposure verified zero, app-side (§1) |
| Schema / migrations | **None** — and read §4 before concluding FR-14 is fixed |
| `scheduler.queued` event type | **None**, unless something enumerates event types |
| `FR-15` | **(b) and (c) shipped upstream. (a) is ours** — §2 |
| `IDEM-11` | **None** — gate still default-off; `register_syscall` can now declare a guarantee |

---

## 1. The removal — verified safe here, not taken on trust

A Nodus guest script can no longer reach subprocess, network, or host environment. **31 builtins**
raise `SandboxError`: 7 subprocess, 18 network (every `http_*` and `_async` variant), 6 host env
(including the writes `env_set` / `env_unset`).

The runtime team measured our exposure as zero. **We re-measured, because their caveat was that
they had checked scripts *as committed*:**

- Every Nodus source in this repo — `apps/analytics/nodus/reasoning_apply_v1.nd` and the
  `.nodus/` tree — scanned for any denied builtin: **no matches**.
- **Nothing generates Nodus source at runtime.** `apps/analytics/bootstrap.py:225` globs packaged
  `.nd` files from disk and registers those; there is no code path that constructs or writes
  Nodus source. That was the specific caveat, and it does not apply to us.

So this breaks nothing here. Recorded in `TECH_DEBT.md`, where the interim
"treat `.nd` content as trusted input" posture is now retired.

If a future script needs one of the denied builtins, the mediated seams are `call_tool(...)`
(enforces the run's scoped capability token) or bare `sys(...)`. Configuration belongs in flow
state or `input_payload`, not host env. **There is deliberately no off switch** — a global one
would re-open the boundary for every run at once.

---

## 2. FR-15 — our defect. Two of three parts shipped, and the third is ours

**The mechanism is confirmed and it is not what a reasonable person would have guessed.**

`_scheduler_heartbeat_tick` is the only thing draining the scheduler queue. It runs on a
**1-second APScheduler job with `max_instances=1`** and dispatched each item **synchronously**,
because `_decide_mode()` returns `INLINE` for everything: Rule 2 short-circuits Rules 4 and 5
whenever `AINDY_ASYNC_HEAVY_EXECUTION` is false — the default. **The entire async path, including
"high-priority work should never block a request thread", was unreachable out of the box.**

Our `maximum number of running instances reached (1)` log was not a side-symptom. It was the queue
being blocked, printing once per starved second. **It predates 2.1.0** — the write-up's refusal to
blame the upgrade was correct, and the runtime team notes it was "stronger than you claimed."

**Shipped in 2.2.0:**

- `scheduler.queued` SystemEvent at enqueue, carrying `queue_depth`, landing in `system_events` —
  the table the original investigation was querying.
- `aindy_scheduler_queue_wait_seconds`, bucketed to **300s** specifically because our observed
  waits (22s / 48s / 184s) would all have fallen into `+Inf` on a default histogram.
- Wait firing moved to **its own job and its own thread**. This also fixed a correctness bug we
  had not spotted: `tick_time_waits()` lived inside `schedule()`, so a slow execution skipped the
  next tick and **no time-based wait fired at all** — a flow parked on a timer stayed parked
  because an *unrelated* flow was busy. The same shared tick is why `/health` died.

> It is `scheduler.queued`, not the `execution.queued` we asked for. Not bikeshedding: the
> execution-contract gate raises for any `execution.*` event emitted outside a pipeline, and the
> two hottest enqueue callers have no pipeline active. **Our requested name would have raised in
> exactly the paths that matter.**

### What is left is ours to trial

Dispatch still runs INLINE by default. 2.2.0 makes the wait *visible* and stops it starving timers
and health; it does not remove it. The remaining step is `AINDY_ASYNC_HEAVY_EXECUTION=1`, now
wired in `docker-compose.prod.yml` (default off, matching the runtime).

**Not flipped in this PR, deliberately.** It changes how every flow, agent, nodus and job
execution is dispatched, and the honest way to evaluate it is to reproduce the Genesis burst
before and after and compare `scheduler.queued` wait times. That is a measurement session, not a
line in an adoption PR.

### Their correction to our write-up — verified, they are right

We cited `flow_definitions.py:254` for the synchronous `execute_infinity` amplifier. **254 is the
decorator; the syscall is at 258, 375 and 554 — three call sites.** Removing one by line number
would have left two. The amplifier fix is still worth doing and is still ours.

---

## 3. IDEM-11 — nothing to do, one thing worth knowing

Declared `EXACTLY_ONCE` syscalls went 1 → 7. Two corrections to earlier information: the registry
holds **23** syscalls, not 27, and the pre-existing declaration was **`memory.write`**, not
`memory.delete` — which inverts the significance, since the guarded call was the busiest write
path rather than an unused one.

**Relevant to us: `register_syscall` had no `execution_guarantee` parameter at all.** `SyscallEntry`
accepted it; the function never forwarded it. So **every syscall this repo registers was
`AT_LEAST_ONCE` with no way to opt in** — the gate was unreachable for app syscalls by
construction. It now works, and a typo raises rather than silently downgrading.

Nothing changes yet: the gate is still default-off (`AINDY_SYSCALL_IDEMPOTENCY`). But when we do
enable it, our own syscalls can now participate — worth an audit of which of ours produce a second
effect on retry.

---

## 4. FR-14 is NOT fixed — read this before concluding otherwise

**The 2.2.0 upgrade will not crash-loop, and that is a property of the release, not a repair.**

2.2.0 contains no schema change: nothing under `AINDY/db/models/`, no migration, schema contract
stays `2026-08-15.1`, Alembic head stays `0016`. So `bootstrap-schema` has no additive drift to
refuse and the bare entrypoint succeeds. **The next release that adds a runtime column reproduces
exactly what took the stack down on 2.1.0.**

Our local guard is unaffected and still the mitigation: `AINDY_BOOTSTRAP_RECONCILE`
(`docker/entrypoint.sh`, default off), plus a refusal that now prints the remedy.

The runtime team flagged this themselves, on the grounds that *"the upgrade worked"* is the
observation most likely to be mistaken for *"the defect is gone."* Repeated here for the same
reason.

---

## 5. Also new

| | |
|---|---|
| `AINDY_SCHEDULER_QUEUE_EVENTS` | default `true` — emits `scheduler.queued`. Set false if volume is unwelcome. Resolved per call, no restart |
| New event type | `scheduler.queued`, roughly one row per enqueued unit |
| New scheduler job | `scheduler_wait_tick`, alongside `scheduler_heartbeat_tick` |
| New metric | `aindy_scheduler_queue_wait_seconds{priority}` |
| New API param | `register_syscall(..., execution_guarantee=...)` |

`scheduler.queued` roughly doubles our per-execution event volume, on a `system_events` table
already at ~160k rows. Not a problem yet; worth watching rather than assuming.

---

## 6. Our scope answer landed

The runtime team recorded the §6 response against `HTTP-SCOPE-GAP-1` and adopted both constraints:
admin scopes tie to the **existing user-row admin flag**, and `execution.read` conflating scope
with data ownership is recorded as a distinct problem. They credit the deciding argument as ours —
that the client already draws the two-privilege-class line (`useAuth().isAdmin`,
`<AdminAccessRequired />`) and it is frontend-only today, so server enforcement formalises an
existing boundary rather than imposing a new one.

**Not in 2.2.0.** When it ships, the handoff will name the scopes being enforced — the thing we
asked for, because a silent narrowing reads as scattered 403s and looks like a frontend bug.

---

## 7. Verification performed

| Check | Result |
|---|---|
| Boot smoke on 2.2.0 | `default-apps`, `app_plugins_loaded=True`, 16 plugins |
| Contract + boundary + model + chunking tests | 61 passed |
| `scripts/check_app_imports.py` | 37 declared, 0 undeclared |
| `ruff check apps/ tests/` | clean |
| Nodus denied-builtin scan | 0 matches across all `.nd` / `.nodus` sources |
| Runtime-generated Nodus source | none — packaged files only |

---

## 8. Open upstream after this release

- **`FR-14`** — unfixed, see §4.
- **`IDEM-12`** (new) — `agent.undo` re-invokes every compensator if called twice and never marks
  effects reversed. **Latent: zero compensators registered today**, so present harm is duplicate
  audit rows only. It goes live the moment anyone registers the first one — worth knowing before
  we register one.
- **`SYSMAX-5`** (new) — ~33 scheduler jobs on a 10-worker pool, counting the runtime's 12 and
  **our 21 `register_scheduled_job` sites**. Latent by construction, not implicated in any
  incident. Relevant to us because adding a scheduled job is cheap and adding a *slow* one is not.
- **`TOOL-SEAM-ISOLATION-1`**, **`EXEC-ENV-BIND-1`**, **`HTTP-SCOPE-GAP-1`** — unchanged.
- **`FR-16`** (filed by us, same day) — 2.2.0 pins `nodus-lang==4.1.0` **exactly**, and
  `nodus-lang==4.2.0` published 2026-08-16. We have no direct dependency on it, so there is no
  app-side route to 4.2.0. Wanted because #376 fixes resume-path correctness bugs on a path we
  run, including a Windows-only store failure and a 200ms resume budget raised to 30s.

**Next available FR number: `FR-17`.**
