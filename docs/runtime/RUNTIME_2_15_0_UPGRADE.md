---
title: "Runtime 2.15.0 upgrade — adoption"
last_verified: "2026-09-14"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.15.0 upgrade — adoption

Floor moved `>=2.14.0,<3.0` → `>=2.15.0,<3.0`; build pin `==2.14.0` → `==2.15.0`; the dependency
contract test asserts the two agree (the handoff says the floor may stay; our test says pin ==
floor, so it moves). Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.15.0.md`.

**This release closes our FR-29** — filed 2026-09-14 from the live Tutorial 2 run recorded in
`RUNTIME_2_14_0_UPGRADE.md` §5, fixed upstream the same day as `WAIT-DETECT-SHAPE-1` (#670).

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `SCHEMA_CONTRACT_VERSION` unchanged at `2026-09-10`;
`git diff v2.14.0..v2.15.0 -- AINDY/db/models AINDY/memory/memory_persistence.py` is empty. The
diff under `AINDY/` is six files: `_version.py`, `requirements.txt` (the eight dependabot bumps),
a `Cargo.lock`, and the three FR-29 files — `core/execution_pipeline/waits.py`,
`kernel/scheduler/persistence.py`, `core/execution_gate.py`. Only the last is a module we import
from, and its change is a docstring on `ExecutionWaitSignal`; our `require_execution_unit` and
`to_envelope` are untouched.

---

## 1. The dev venv, re-checked printing the path

```
2.14.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.15.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -c constraints.txt --no-cache-dir
```

**The first two installs failed with the same `IncompleteRead(17281 bytes read, 273 more
expected)`** and left the venv on 2.14.0 — at which point `test_the_interpreter_runs_a_runtime_
inside_the_declared_range` failed, which is exactly the situation it was written for (the pin
said 2.15.0, the interpreter said 2.14.0). An identical byte count twice is not a flaky link; it
is a poisoned pip cache entry. `--no-cache-dir` fixed it on the first try. If an install fails
with the *same* numbers twice, reach for that before retrying a third time.

---

## 2. Gained on adoption — FR-29 closed, and two things our diagnosis could not see

- **`_detect_wait` honours `ExecutionWaitSignal` only.** The dict branch (any handler result with
  `status: "WAITING"`) is gone. A request's execution unit describes the request and completes
  when the handler returns; the run it read or started carries its own wait.
- **`_persist_wait_backup` checks the id names a `flow_runs` row first.** A non-run id is a DEBUG
  skip, not the `ForeignKeyViolation` WARNING that read like data loss.
- **Our "legitimately parked" `nodus/run` half never was.** The dict branch was written for a
  suspending script and never worked: `_format_execution_response` nests `waiting_for` under
  `data`, so it parked the request on the literal event `"unknown"` — and nothing has ever
  re-executed a returned request, so the dict path parked units and never resumed one, on any
  release. Our two `job|route` rows on `"unknown"` were that; so, almost certainly, were the 105
  `route` units the runtime's own 2026-09-13 tutorial run left behind.
- **Our `flow_run_get` result key stays.** It no longer arms anything, and the owner's decision
  (2026-09-14) was to keep it as the direct test path — the app-profile container is the one
  deployment where the bare-row shape reaches the pipeline, so it is where the fix is proven live.
- One precision on our census: `getFlowRun` **is** exported — `client/src/api/operator.js:12`
  and again through `client/src/api.js:34` — which `grep flows/runs` cannot see. Neither export
  has a caller, so "nothing of ours calls the route" holds, by two dead exports.

---

## 3. Consumer-visible edges, checked against our source — none fire

| Change | Where we would feel it | Our source |
|---|---|---|
| Envelope of `POST /platform/nodus/run` (any route returning a `WAITING` record) is now top-level `status: "success"` with `data.status: "WAITING"`; was `status: "waiting"` + `metadata.eu_wait_for: "unknown"` | code branching on the envelope's top-level `status` or on `eu_wait_for` | the four routers the handoff names read `result.data.get("status")` (`goals_router.py:40`, `leadgen_router.py:60`, `research_results_router.py`, `freelance_router.py:68`) — unaffected; `eu_wait_for` → 0 hits in `apps/` and `client/src` |
| A request that reads/starts a waiting run traces `execution.completed`, not `execution.waiting` | the rippletrace causal graph for such a request | the run's own `flow.waiting` event is unchanged — that is the wait |
| `execution_units` stops gaining a `waiting` row per read of a parked run | `ExecutionConsole.jsx`'s `waiting` filter; anything counting units by status | the count stops growing; the rows already there stay unless retired (§5 step 3) |
| `[Scheduler] waiting backup write failed … ForeignKeyViolation` stops on reads | log noise only | — |
| `click` 8.5.0, `jiter` 0.16.0, `psycopg2` 2.9.13, `tqdm` 4.70.1 | nothing expected | `constraints.txt` pins only `aindy-runtime`; these resolved through it (`Successfully installed … click-8.5.0 jiter-0.16.0 psycopg2-2.9.13 tqdm-4.70.1`) |

**Not touched, correctly:** `task_service.py:582` moves a *task's own* unit to `waiting` on
pause — a unit we own describing a thing we are waiting on, the opposite of the defect.

---

## 4. Not taken: nothing new is flagged

No new opt-in knob. The 2.13.0 knobs stay off for the reasons in `RUNTIME_2_13_0_UPGRADE.md` §4.

---

## 5. Verification

### Dev venv, 2026-09-14

```
venv imports 2.15.0 from site-packages (path printed)               — §1
test_runtime_dependency_contract.py                                 — 6 passed
app-profile subset (seven CLAUDE.md files, -m app_profile)          — 55 passed
boot smoke: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16; 98 syscalls
ruff check apps/ tests/ — clean;  check_app_imports.py — 37 declared, 0 undeclared
```

**Full `tests/unit` on the installed 2.15.0 (2026-09-14, this venv, path printed):** `1240 passed, 1 skipped, 382 warnings, exit 0` — read from the summary line of the log file, not from progress dots.

<!-- CONTAINER_RESULT -->
