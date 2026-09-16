---
title: "Runtime 2.19.0 upgrade — adoption"
last_verified: "2026-09-16"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.19.0 upgrade — adoption

Floor moved `>=2.18.0,<3.0` → `>=2.19.0,<3.0`; build pin `==2.18.0` → `==2.19.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.19.0.md`.

**This release closes the runtime half of our `SYSCALL-SILENT-ERRORS-1`** (#365) — picked up
from the commit body, not from an FR, and fixed upstream as `SYSTEM-STATE-TENANT-1` (#692). It
also corrects an inference that entry made (§2).

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `SCHEMA_CONTRACT_VERSION` unchanged at `2026-09-10`;
`git diff v2.18.0..v2.19.0 -- AINDY/db/models AINDY/memory/memory_persistence.py alembic/` is
empty. The diff under `AINDY/` is 13 files (+319 / −270). Of those, we import from three —
`kernel/syscall_dispatcher.py`, `kernel/syscall_registry.py`, `services/auth_service.py` — and
the symbol-level change in each is additive (`is_api_key_principal`, `is_operator_principal`
added; one handler removed). Every symbol we import from them (`SyscallContext`,
`dispatch_syscall`, `get_dispatcher`, `make_syscall_ctx_from_*`, `SYSCALL_REGISTRY`,
`get_registered_syscalls`, `get_current_user`, `verify_api_key`, `hash_password`) is unchanged.
The removed syscall `sys.v1.agent.list_recent_durations` → 0 hits in `apps/`, `tests/`,
`client/src`.

---

## 1. The dev venv, re-checked printing the path

```
2.18.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.19.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -c constraints.txt --no-cache-dir
```

---

## 2. Gained on adoption — the system-state snapshot is whole again, and our entry was wrong about why it broke

`compute_current_state()` (runtime `system_state_service`) dispatched `sys.v1.agent.count_runs`
and `sys.v1.agent.list_recent_durations` with `user_id=None`. Our `SYSCALL-SILENT-ERRORS-1`
close-out recorded that correctly and inferred two things the source does not support. Both are
corrected in `TECH_DEBT.md` under that entry, and here:

- **"Inside a request the pipeline's tenant context covers an empty ctx" — nothing does.** No
  ContextVar fills `SyscallContext.user_id`; the dispatcher refused those two dispatches on
  *every* call, request or job. Our route probes "succeeded" because no runtime route calls
  `compute_current_state` — our three callers (`apps/agent/agents/triggers.py:92`,
  `apps/analytics/services/integration/dependency_adapter.py:138`,
  `apps/masterplan/agents/ranking.py:39`) are the only ones anywhere.
- **Passing a tenant was not the fix.** Both syscalls scope to one user by construction and the
  snapshot is a whole-system reading. 2.19.0 reads `AgentRun` directly, the way `FlowRun` always
  was in the same function.

**What changes for us, unflagged and on adoption:** `active_runs` now includes agent runs in
`approved | executing | pending_approval`, and `avg_execution_time` includes agent durations —
both had been silently zero since 2.0.0. `system_load` and `health_status` derive from them.
Where we read those:

| Reader | What it does with the number |
|---|---|
| `apps/agent/agents/triggers.py:31,39,62,72` | `system_load` and `health_status` weight trigger priority; `critical` suppresses importance < 0.9 |
| `apps/masterplan/services/goal_service.py:70-82,244` | `critical` demotes operational goals; `system_load >= 0.75` demotes learning goals; ranking tie-break on load |
| `apps/analytics/services/integration/dependency_adapter.py:138` | passes the snapshot through to the Infinity dependency adapter |

None of those thresholds was tuned against measured numbers — they are the shipped constants —
so there is nothing to re-tune. On a deployment with agent traffic the snapshot reads higher
load and a less calm health status. **That is the true reading, not a regression**; the one
agent and five runs ever on the local stack (`agent-tools-and-runs`) make it a non-event here.

---

## 3. Consumer-visible edges, checked against our source — none fire

| Change | Where we would feel it | Our source |
|---|---|---|
| `sys.v1.agent.list_recent_durations` removed (#693, DEC-022); `SYSCALL_REGISTRY_MIN_COUNT` 24 → **23** | a dispatch of it; a test pinning the registry count | 0 dispatches. App-profile boot: **97** syscalls (was 98) = 23 runtime + 74 ours, so our count is unchanged. `CLAUDE.md` re-derived |
| `AINDY_NODUS_MAX_MEMORY_MB` (#697) — per-execution Nodus guest memory ceiling, **unset = unchanged** | `execute_nodus_task_payload` (`apps/memory/bootstrap.py`) | untouched by the runtime. **Left unset** (§4). Applies to the guest path only; API-process agent runs and flow nodes stay unbounded (`SYSMAX-3` open upstream) |
| Plugin-host post-launch check failure kills the worker on every path (#694) | `strong_sandbox_vm` / hostile hosts | we run neither |
| `sys.v1.agent.undo` re-entrant, response gains `already_reversed` (#696) | a second undo | we dispatch no `agent.undo`; no compensator registered |
| Boot-time route AST validator deleted (#698, DEC-023) | boot log shape | the request-time wrapper was always the only enforcement; our `pre-pipeline-raise` guard scans our own modules and does not use it |
| Admin guards share `is_operator_principal`; tenant-path validators share one rule (#699) | `require_platform_admin_access` on `/platform` | still admits any API key there, by design; we import none of the four changed symbols |

**Not touched:** the pipeline envelope, `require_execution_unit`, `to_envelope`, `register_tool`,
`run_flow`, every route path and status code we consume.

---

## 4. Decisions recorded, not taken

### 4.1 `AINDY_NODUS_MAX_MEMORY_MB` — left unset

It bounds *growth* over a run, polled, so a single large allocation still escapes it; the handoff
says to set an OS-level cap alongside. `docker-compose.prod.yml` sets no memory limit on `api`
(only `mongo` has `mem_limit: 768m`), and the host's reinit floor is 457–726 MB on 7.7 GB soldered
RAM — a guest ceiling without a container cap protects nothing, and a container cap on this host
is a separate decision with the `POSTGRES-CRASH-RESIDUAL-1` history behind it. Nothing writes to
the guest path with `AINDY_REASONING_NODUS_NATIVE` off (the soak gate), so there is no run to
bound yet. Revisit with the flip.

### 4.2 DEC-021 — `waiting → completed` stays not-an-edge; our task hook's shape is an owner's call

Our `TASK-EU-NOT-PERSISTED-1` fix (#363, `task_service.py:716-723`) steps a paused task's unit
`waiting → executing → completed`. The runtime declined to add the edge: `waiting` on a unit
means *parked on an event the scheduler will deliver*, and a paused task is parked on nothing —
no `wait_condition`, not in the scheduler; nothing will ever wake it. The workaround **keeps
working** (the `waiting → executing` edge is the runtime's own gate re-entry). What it costs is
audit honesty: the path skips `resumed` and leaves a zero-duration `executing`.

Two truthful shapes, no urgency:

1. **Don't move a paused task's unit to `waiting`** — from the runtime's view a paused task is
   still in flight. Drop the pause hook's `update_status(..., "waiting")` and the complete hook's
   step-through. Also worth knowing: `start_task` on a paused task answers *"already started"*
   (`start_time` is set), so there is no un-pause path today — a paused task's only exit is
   `complete`.
2. **Call `ExecutionUnitService(db).resume_execution_unit(eu.id)`** before
   `update_status(..., "completed")` in the complete hook. Idempotent, two-step
   (`resumed → executing`), clears `wait_condition`. One line, and
   `test_task_execution_unit_persistence.py` already pins the shape.

**Taken: (2), the day after this pass.** `complete_task`'s hook now calls
`resume_execution_unit` when the unit is `waiting`, and
`test_task_execution_unit_persistence.py` pins the sequence `resumed → executing → completed`
(mutation-checked: the old shape fails it). Shape (1) was not taken because a paused task's
unit *should* read as not-in-flight while paused — that is what the pause is — and the only
cost of `waiting` was the exit path, which is now the runtime's own.

---

## 5. The two 2.17.0 asks — unchanged, still owner's calls

`RUNTIME_2_17_0_UPGRADE.md` §3: named predicates behind a drain (#680); one tool declaring
`on_denial="wait"` (#681). Nothing in 2.19.0 changes their shape or cost.

---

## 6. Verification

### Dev venv, 2026-09-16

```
venv imports 2.19.0 from site-packages (path printed)               — §1
test_runtime_dependency_contract.py                                 — 6 passed
app-profile subset (seven CLAUDE.md files, -m app_profile)          — 55 passed
boot smoke: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16; 97 syscalls
ruff check apps/ tests/ — clean;  check_app_imports.py — 37 declared, 0 undeclared
```

**Full `tests/unit` on the installed 2.19.0 (2026-09-16, this venv, path printed):** `1274 passed, 1 skipped, exit 0` — counted from the log (`addopts = -q` plus `-q` suppresses the summary line; 1274 dots, one `s`).

### Container rebuilt and verified

### Container rebuilt and verified (2026-09-16 21:45 UTC, same session)

Stack was down from the previous session (image `019adbc002fa` carried #369 but not #370/#371).
Pin bump → `docker compose … build api` → image `808b89e18fd6`, `Successfully installed …
aindy-runtime-2.19.0`, pip layer 83 s warm → stack up. Boot ran the app migration
`lc1contact001 → pc1pace0001` (the pace proposal's two columns); runtime schema `0018`, no change.

**A 26-minute detour that was not the release.** The first `up` used the documented
single-instance form (both compose files, no profiles). The api sat `unhealthy` with `/health`
→ `500 internal_error` while `/api/version` answered — the rate limiter's Redis storage
(`REDIS_URL` is hardcoded in `docker-compose.prod.yml`; `redis` is `profiles: ["full"]`) raising
on an unresolvable name, on every `@limiter.limit` route. **A/B'd in-process against the same
network: the 2.18.0 image (`d02181cdf2ac`) answers the same 500.** Every live stack since 2.13.0
had been brought up `--profile full --profile mail`; this one was not. Filed as
`COMPOSE-REDIS-URL-UNCONDITIONAL-1`; re-`up` with the profiles → `healthy`. The 88
`error.unhandled_request` events the healthcheck generated in that window are visible in §6
step 3 below and age out with the snapshot's one-hour window.

Handoff §6, each read rather than assumed:

| §6 check | Result |
|---|---|
| 1. version + path, in the container | `2.19.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| 2. `bootstrap-schema` | exit 0 — `runtime-owned tables already present`, stamped `0018` |
| 3. ★ **the snapshot counts agent runs** — 7 `pending_approval` agent runs in the table (all 2026-09-13), 0 active flow runs | `active_runs 7, avg_execution_time 961.38, system_load 0.4906` — it was `active_runs 0` by construction before. `health_status critical`, but from `failure_rate 0.77` (the 88 healthcheck 500s above; `dominant_event_types[0] = error.unhandled_request × 88`), not from the agent runs: the load term is 0.49 against `degraded_load 0.65`. `TENANT_VIOLATION` in the log: **0**; `list_recent_durations` in the log: **0** |
| 4. the removed syscall through `POST /platform/syscall` (test account promoted, then reverted; body field is `name`, not `syscall` as the handoff writes it) | `404 {"error":"http_error","message":"Request failed","details":{"error":"Unknown syscall: 'sys.v1.agent.list_recent_durations'"}}` — the standard envelope, not a 500. Control `count_runs` → `403 … requires capability 'agent.read'; caller has []` (a user JWT carries no capabilities; the route's scope gate is doing its job) |
| 5. readiness with the smaller floor | `/health/deep` `syscall_registry: {status: ok, count: 97, minimum_expected: 23}`, `status: healthy` |
| boot log at WARNING, on a clean restart with redis present | **7 lines, all the usual** (`APP_DEPENDS_ON` ordering gap ×2, twice — the graph imports twice; `STRIPE_WEBHOOK_SECRET` twice; `MAX_CONCURRENT_PER_USER=0`), 0 ERROR / Traceback, 0 `TENANT_VIOLATION`, 0 `list_recent_durations`. Nothing new |

**One thing §6 step 3 surfaces that is ours to decide:** the 7 `pending_approval` agent runs
from 2026-09-13 now count as active forever — `+0.23` on `system_load` for as long as they sit
there — and nothing expires them. Approve, reject or delete them; the snapshot our triggers and
goal ranking read is the honest one only once the table is.

**Decided: approved, all seven, 2026-09-16 22:08–22:15 UTC, as their owner (`shawn@local.test`,
token minted in-container).** Snapshot afterwards: `active_runs 0, health_status healthy`. What
running them showed:

| runs | plan | result |
|---|---|---|
| 1 | `memory.recall` | completed 1/1 in 24 s — 5 nodes of telemetry (`execution.started from agent`, sim 0.86) for the query "cost governor phase 2" |
| 2 | `memory.recall → reasoning.evaluate` | completed 2/2 in 3 s — `reasoning.evaluate` returned the canned Next-Action (`review_plan`), not a synthesis; the planner chose it on its name |
| 4 | `memory.recall → arm.analyze` | **failed**: `sys.v1.arm.analyze requires 'file_path'` — the planner sent `{"topic": …}` because the description said "code or a topic" |

### The file-path run (#375 → #376 → this), 2026-09-16 23:18–23:20 UTC

Same objective (*"Analyze the file apps/arm/agents/tools.py with ARM and summarise what it does
in one sentence"*), test account, rebuilt image each time:

| image | plan | outcome |
|---|---|---|
| `f9ba89598710` (#375) | `arm.analyze {"file_path": "apps/arm/agents/tools.py"}` → `memory.write` — **the right key, first try** | `failed`: `400 The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed gpt-4o` → `ARM-MODEL-NAME-PROVIDER-MISMATCH-1` (#376) |
| `406b27d96ad1` (#376) | same | **`completed 2/2` in 41 s.** `arm.analyze` → architecture 8, integrity 6, a real summary, `analysis_results` row (`deepseek-v4-pro`, 1201/764 tokens, 15.2 s) — **ARM's first analysis on any stack**; `memory.write` → node written |

And what the successful run's *telemetry* showed, which is where the next three came from:

- `/metrics` after the run: only the planner's `anthropic` pair (`attributed="unit"`). **No
  DeepSeek sample at all**, `aindy:rm:tenant:<test-account>:tokens` = 5876 = exactly the two
  planner calls, `score.computed.llm_tokens: 0`. The run's `flow_run` is
  `nodus_execute / nodus_agent_execution` and `aindy_nodus_warm_pool_events_total{served}`
  ticked at its completion: our `apps/agent/bootstrap.py` defaults the backend to `nodus_vm`,
  so tool steps run in the worker process and are metered there. **FR-35.** The 2.13.0 §3
  reading — *"`run` only appears once a step calls an LLM"* — is true only on `agent_flow`.
- `[AgentRuntimeExtensions] Agent completion orchestrator failed … user_id is required` at
  completion — the runtime passes `user_id` as a `uuid.UUID`, the boundary redacts it, our hook
  passed the redaction to the Infinity job. 8 of 8 completed runs ever; none `loop_enforced`.
  **`AGENT-COMPLETION-HOOK-USERID-1`** (ours, #377) + **FR-36** (theirs, one `str()`).
- `[EU] invalid transition completed→completed` at finalize — the runtime completes the run's
  unit twice; noise, not filed.

Three findings, one ours: every app tool's description now carries `Args: {…}` and
`test_agent_tool_descriptions_declare_args.py` enforces it (this was the only channel the planner
has — **FR-33** asks for a real one); `steps_completed` reads 2/2 on every failed run and lands in
`score.computed` that way (**FR-34**). No LLM call was minted by any of the seven, so
`attributed="run"` (2.13.0 §3) is still unobserved — the `arm.analyze` runs would have been the
first, and they fell over before the seam.

