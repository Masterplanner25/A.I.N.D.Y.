---
title: "Runtime 2.14.0 upgrade — adoption"
last_verified: "2026-09-14"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.14.0 upgrade — adoption

Floor moved `>=2.13.0,<3.0` → `>=2.14.0,<3.0`; build pin `==2.13.0` → `==2.14.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.14.0.md`.

The handoff says the floor *may* stay at 2.13.0. It moves anyway: `test_constraint_pin_equals_the_floor`
requires pin == floor, and the four fixes below are worth guaranteeing present wherever the app is
installed.

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `SCHEMA_CONTRACT_VERSION` unchanged at `2026-09-10`;
`git diff v2.13.0..v2.14.0 -- AINDY/db/models AINDY/memory/memory_persistence.py` is empty. The
three `alembic/versions/` files in the diff each change one docstring path
(`IDEMPOTENCY_AUDIT.md` → `docs/archive/…`, `docs/runtime/…` → `docs/design/…`) — no DDL.

The diff under `AINDY/` is 34 files. Five are modules this repo imports from; **none of the
symbols we take changed**:

| Module we import | What changed in it | Our symbols affected |
|---|---|---|
| `platform_layer/async_job_service.py` | adds `AsyncJobHandlerNotRegistered`, `_schedule_job_retry` (backoff for thread-mode retries); attempt numbered before the handler lookup | `build_deferred_response`, `defer_async_job`, `register_async_job`, `submit_autonomous_async_job` — unchanged |
| `kernel/event_bus.py` | `publish()` / `publish_event()` gain optional `run_id=None`; wire payload gains a `run_id` key | `get_event_bus` — unchanged |
| `agents/tool_registry.py`, `core/execution_gate.py`, `kernel/syscall_dispatcher.py` | comment-only (doc path renames) | — |

Nothing removed anywhere. The other 29 changed files (flow runner, scheduler waits, event
router, nodus adapter, resource manager, two new `.nodus` samples) are modules we do not import.

---

## 1. The dev venv, re-checked printing the path

```
$ venv/Scripts/python.exe -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
2.13.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.14.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -c constraints.txt
```

Everything in §5 ran against that 2.14.0.

---

## 2. Gained on adoption, nothing to wire — four WAIT/resume and job-retry fixes

All four were found by the runtime team running their own tutorials live against 2.13.0.
Each claim about *our* source below was re-derived here, not copied from the handoff.

- **A suspended Nodus script now receives the payload that resumed it** (#654). The flow runner
  used to merge SUCCESS node patches only, so a guest's WAIT patch never reached the run's state
  and the resume payload was dropped. `nodus_wait_requested` → **0 files under `apps/`**: we run
  no guest script that waits, so this is capability we did not have, not behaviour that moved.
- **`POST /platform/flows/runs/{id}/resume` resumes that run only** (#655). It used to wake every
  run parked on the event name, any tenant. Our `POST /apps/agent/runs/{id}/resume` wakes by the
  agent run's `run_<uuid4>` correlation — unique per run — so it was never affected.
- **A waiting flow run no longer holds a tenant concurrency slot** (#656). Four parked waits
  used to 429 the whole tenant (`AINDY_QUOTA_MAX_CONCURRENT`, default 5). Not a cap raise. Our
  `WaitRecovery` sweep (`apps/tasks/bootstrap.py:384`,
  `scheduler.notify_event(row.event_type, correlation_id=row.correlation_id)`) is untouched —
  the new `run_id` kwarg is optional.
- **An async job whose handler is not registered fails once, terminally** (#657). It was
  re-dispatched in-process ~87×/s forever. We register **23** handlers (`register_job(` → 23
  call sites) and submit no jobs directly (`dispatch_job` → 0), so the only way we meet this
  is a `job_logs` row naming a handler we have renamed or stopped loading — it now fails on its
  first attempt with `AsyncJobHandlerNotRegistered` in `error_message` instead of flooding the
  log.

---

## 3. Consumer-visible edges, checked against our source — none fire

| Change | Where we would feel it | Our source |
|---|---|---|
| A custom node's WAIT `output_patch` now lands on the run's state | any node returning `{"status": "WAIT", …, "output_patch": …}` | our one WAIT node, `genesis_track_message` (`apps/automation/flows/flow_definitions.py:206`), returns `{"status": "WAIT", "wait_for": "genesis_user_message"}` — no patch; it reads `state["event"]`, which the resume route still injects |
| Nodus execution record's `nodus_status` is `"waiting"` on a WAIT, not `None` | code branching on `nodus_status is None` | `apps/analytics/services/reasoning/nodus_apply.py:75` tests `!= "success"` — unaffected |
| Event-bus Redis message gains a `run_id` key (additive) | a 2.13.0 and a 2.14.0 instance sharing Redis mid-deploy | `api` and `worker` build from one image; a mixed pair only exists if rolled separately |
| `ExecutionUnit` rows for parked flow runs read `waiting`, not `executing` | dashboards counting `executing` EUs | our two `"executing"` writes (`apps/tasks/adapters.py:47`, `task_service.py:552`) are task-status mappings, not EU counts; a lower `executing` count for parked runs is correct |
| `AINDY_RETRY_BACKOFF_BASE_MS` / `_MAX_MS` now apply to thread-mode job retries | jobs submitted with `max_attempts > 1` | our five `defer_async_job` / `submit_autonomous_async_job` call sites pass no `max_attempts`; the three `max_attempts` reads under `apps/automation/` are our own `AutomationLog` column |

---

## 4. Not taken: nothing new is flagged

No new opt-in knob this release. The three 2.13.0 knobs (`AINDY_QUOTA_MAX_TENANT_TOKENS`,
`AINDY_QUOTA_MAX_TOKENS`, `AINDY_RUN_SCOPED_QUOTA`) stay off for the reasons in
`RUNTIME_2_13_0_UPGRADE.md` §4. `AINDY_RETRY_BACKOFF_BASE_MS=0` would restore immediate
thread-mode retries; we have no reason to want that.

---

## 5. Verification

### Dev venv, 2026-09-14

```bash
# venv imports 2.14.0 from site-packages (path printed) — §1
venv/Scripts/python.exe -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
#  got: 2.14.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']

# declared range and pin agree, and the interpreter satisfies them
venv/Scripts/python.exe -m pytest tests/unit/test_runtime_dependency_contract.py -q
#  got: 6 passed

# app-profile subset (the seven CLAUDE.md files, -m app_profile)
#  got: 55 passed

# app-profile boot smoke (CLAUDE.md block)
#  got: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16; 98 syscalls
```

**Full `tests/unit` on the installed 2.14.0 (2026-09-14, this venv, path printed):** `1240 passed, 1 skipped, exit 0` in 116 s — read from the summary line of the log file, not from progress dots. `ruff check apps/ tests/`: clean. `scripts/check_app_imports.py`: 37 declared, 0 undeclared.

### Container rebuilt and verified (2026-09-14, same day)

`docker compose ... build api` (no `--no-cache` — the pin move invalidates the pip layer by
itself; apt stayed cached) → image `41642f6427f3`, `Successfully installed … aindy-runtime-2.14.0`.
The pip layer alone took 968 s on this link. Full stack up (`--profile full --profile mail`,
both compose files) with **430 MB** host memory available — under the documented reinit floor —
and it still came up `healthy` with 0 restarts. Every handoff §4 check, each read rather than
assumed:

| Handoff check | Result |
|---|---|
| 1. version + path in the container | `2.14.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| 2. `aindy-runtime bootstrap-schema` | exit 0; heads runtime `0018`, app `ga1shadow0001` — unchanged |
| 3. job storm on boot | `failed TERMINALLY` 0, `is not registered` 0 — and still 0 after 12 h up and the tutorial. `[job_recovery] re-dispatched 3 orphaned thread-mode job(s)` at boot, all three handlers registered |
| 4. ★ **Tutorial 2, Steps 1–6, live** | **passes — see below** |
| 5. parked runs cost nothing | with a run `waiting`, four `GET /platform/flows/runs/{id}` → `[200, 200, 200, 200]` |
| `/api/version` | `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16` |
| logs after boot + tutorial | 0 postgres reinits, 0 tracebacks; 7 scheduler-saturation lines in 12.5 h, single and hours apart (idle noise on a 430 MB host, not the wedge fingerprint) |

#### Tutorial 2 end to end — the first live run of it anywhere (owner-approved, test account)

Run as the designated test account, promoted to `is_admin` for the duration (every route on that
page is `platform.admin`) and **reverted afterwards** — the frontend-walk precedent. Script and
`.nd` are the tutorial's verbatim; our harness logs in with a password instead of an admin key
and accepts both the documented envelope and the bare shapes this runtime actually returns.

```
Starting script (phase 1 - will suspend)...
  Run id:       f40116a3-…      Flow status: WAITING      Nodus status: waiting   ← was None on 2.13.0 (handoff §2 row 2)
Flow run: status=waiting waiting_for=review.approved
Pending node written in phase 1:  • Pending review: 3 tasks loaded for sprint-12

Approving...
  {'run_id': 'f40116a3-…', 'resumed': True, 'results': [{'run_id': 'f40116a3-…', 'payload_injected': True}], …}
  results entries: 1                                                           ← #655: exactly one

Watching the run after resume...
  status=success   waiting_for=None  received={'review.approved': {'reviewer': 'shawn', 'approved': True, 'note': 'Ship it.'}}
  history: ['WAIT', 'SUCCESS', 'SUCCESS']
  nodus_output_state: {'nodus_received_events': {…}, 'outcome': 'approved'}
Insights:  • Sprint-12 tasks approved by shawn. Note: Ship it.   tags: approved, sprint-12, shawn
```

That is the handoff's "after the fix" output — #654 (payload reached the script), #655 (one
`results` entry), #656 (four GETs 200 while parked) in one pass. Two things to know that the
handoff's one line does not say:

- **`history` has three rows, not two, and that is correct.** The `nodus.execute` node's rows are
  exactly `['WAIT', 'SUCCESS']`; the third `SUCCESS` is `nodus_record_outcome`, the runtime's own
  follow-on node (`AINDY/runtime/nodus_adapter.py`), which runs once the script completes. Read
  the node names, not just the statuses, before filing `['WAIT','SUCCESS','SUCCESS']` as a defect.
- **#655 was checked with a second run parked on the same event.** A first attempt had left run
  `2b7ef96f…` waiting on `review.approved`; resuming `f40116a3…` left it `waiting` (on 2.13.0 it
  would have been woken too). It was then resumed with `approved: false` → `success`,
  `outcome: rejected` — the other branch of the script works as well. 0 waiting runs left.

#### Found while looking: FR-29

Eight `[Scheduler] waiting backup write failed … ForeignKeyViolation … waiting_flow_runs_run_id_fkey`
WARNINGs — one per read of the parked run — and ten `execution_units` rows stuck `waiting`
(eight `flow|route`, two `job|route`) after both runs had finished. The "run id" in each
warning is the **GET request's own execution-unit id**: the pipeline's `_detect_wait` reads the
returned run row's `status: waiting` as the request itself waiting. Pre-existing (none of the
three files involved changed in 2.14.0), not a regression — **but armed by us**: our
`register_flow_result("flow_run_get", result_key=…)` (`apps/rippletrace/bootstrap.py:148`) is what
puts the bare row, `status: waiting` and all, where the detector reads; on a platform-only server the
row is nested and the detector never fires, which is why the tutorial reads `data.flow_run_get_result`
and the runtime team never saw it. Filed as `RUNTIME_FEATURE_REQUESTS.md` **FR-29** with the
mechanism, the ask, and the one-line app-side sidestep (owner's call — it changes a response shape).
