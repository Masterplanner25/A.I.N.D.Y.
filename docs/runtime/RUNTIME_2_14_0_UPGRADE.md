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

### In the container, after the rebuild — owed

The image is still `d79a5bc9060f` (2.13.0). `constraints.txt` is `COPY`'d before the pip `RUN`,
so a plain `docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml --profile full
--profile mail build api` invalidates the pip layer by itself; `--no-cache` buys re-running apt
(~25 min on this link, `RUNTIME_2_13_0_UPGRADE.md` §5) and nothing else. Then, from the handoff §4:

```bash
# 1. on 2.14.0, path printed
docker exec <api> python -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
#    expect: 2.14.0 ['/usr/local/lib/python3.11/site-packages/AINDY']

# 2. no schema drift
docker exec <api> aindy-runtime bootstrap-schema      # exit 0

# 3. no job storm on boot — at most one line per stale job_logs row, then silence
docker logs <api> 2>&1 | grep -c "failed TERMINALLY"
docker logs <api> 2>&1 | grep -c "is not registered"   # must not keep growing

# 4. ★ Tutorial 2 end to end (aindy-runtime docs/tutorials/02-event-driven-automation.md, Steps 1–6)
#    expect: status=success  received={'review.approved': {...}}   history: ['WAIT', 'SUCCESS']
#    and exactly ONE entry in the resume response's `results`. Exercises #654, #655, #656 in one pass.
#    If it does not produce ['WAIT', 'SUCCESS'], file it against the runtime with the run's history —
#    do not debug the tutorial.

# 5. parked runs cost nothing — with a run waiting (Step 5), four read-only GETs for the tenant all 200
```

Step 4 is the one that matters: none of the four fixes has been re-run against a live server yet,
and our rebuilt container is the first one that can.
