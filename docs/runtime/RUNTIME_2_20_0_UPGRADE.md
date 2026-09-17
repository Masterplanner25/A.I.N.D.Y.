---
title: "Runtime 2.20.0 upgrade — adoption"
last_verified: "2026-09-17"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.20.0 upgrade — adoption

Floor moved `>=2.19.0,<3.0` → `>=2.20.0,<3.0`; build pin `==2.19.0` → `==2.20.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.20.0.md`.

**This release ships all five FRs we filed against 2.19.0** — FR-32 … FR-36, four of them filed
the day before — plus one schema step, which is **the first exit-3 reconcile this stack has ever
taken** (§6.2: the 2.3.0 handoff asked for the path to be proven and nothing since had exercised
it). One code change taken on adoption, because the release forced a test to change anyway and
the honest change was the take, not the patch: FR-32 option 2 (§2). One defect found on the way,
pre-existing and ours-and-theirs (§7, FR-39).

Verified rather than taken from the handoff: `git diff v2.19.0..v2.20.0 -- AINDY/ alembic/` is 38
files (+2130 / −225). We import from 13 of them; every symbol we import is unchanged and every
change at the seams we touch is additive — `register_tool` gains `args_schema=None`,
`platform_layer.registry` gains `register_event_retention`, `flow_definitions` gains
`register_default_flows`, `metrics` gains five series. Schema: `background_task_leases.fence`
(model, `0019`, `SCHEMA_CONTRACT_VERSION 2026-09-16`) and nothing else under `db/models`.

---

## 1. The dev venv, re-checked printing the path

```
2.19.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.20.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -e .[test] -c constraints.txt --no-cache-dir
```

---

## 2. FR-32 — taken on adoption: `memory_execute_loop` is ours, the orchestrate node is gone

The runtime's `memory_execute_loop` is now a **default**: `register_default_flows()` runs after
plugin flows on both boot paths (`startup._register_flow_engine`, `worker/__main__`), so a
plugin's registration wins. That moved the graph out of `register_all_flows()`, which broke
`test_memory_execute_no_recalc.py::test_the_runtime_graph_still_resolves_its_terminal_node`
(`KeyError: 'memory_execute_loop'`) — a test whose docstring began *"Until FR-32 lands"*.
Patching it to say the same thing on the release where FR-32 landed was the wrong change.

**Taken:** `apps/automation/flows/flow_definitions.py::register_all_flows` registers
`memory_execute_loop` as `memory_execution_validate → memory_execution_run` (the same two-node
shape as our `memory_execution`), and `memory_execution_orchestrate` — the pass-through body
`MEMORY-EXECUTE-LATENCY-1` left in place only because the runtime's graph named it — is
**deleted**. The test file now pins: the node is absent from the module and `NODE_REGISTRY`;
both graphs and the bootstrap plan end at `run`; no recalc is reachable from the two nodes that
remain; and, reproducing the 2.20.0 boot order, `register_default_memory_execute_loop()` returns
`False` with our graph in place and the displaced default was the three-node shape that scored.

In the container (§6.4): `FLOW_REGISTRY["memory_execute_loop"]` is the two-node graph,
`memory_execution_orchestrate` is not registered, the default reports it stood down. `POST
/memory/execute` runs our shape.

---

## 3. The other four FRs — what each changes for us, read on the live stack

| FR | Shipped as | What we saw (§6) |
|---|---|---|
| **FR-36** (#708) | completion-hook `user_id` is a `str`; a boundary test for the hook builder's documented keys | 0 `user_id is required` on two new runs; `loop_enforced: true`, `next_action.chosen` recorded. Our `AGENT-COMPLETION-HOOK-USERID-1` fix (tenant from the re-fetched run) is kept and is no longer load-bearing. **The fix covers one of three hook contexts** — §7 |
| **FR-34** (#708) | `steps_completed` counts steps that succeeded, both backends (our filing named `agent_flow`'s sites; `nodus_vm` had four more) | a run failing at step 1 of 2 reads **`steps_completed 0, steps_total 2, current_step 1`**, and `score.computed.dimensions.steps_completed` is 0 with it. Under 2.19.0 that row read 1. `Assistant.jsx:268` / `AgentConsole.jsx:134` need no change — they were reading the wrong number, now they read the right one |
| **FR-33** (#709) | `register_tool(..., args_schema={...})`; catalog renders `args={…}`; `execute_tool` validates under `AINDY_TOOL_ARGS_VALIDATION` (`warn`) | at adoption: 15 tools, **0 with a schema**, `aindy_tool_args_validation_total` no samples. Declared on all 15 the same day (§5.1); the counter starts moving at the next rebuild |
| **FR-35** (#712) | tool-step LLM usage on `nodus_vm` rides the worker reply; recorded in the api process | **First DeepSeek sample `/metrics` has ever served**: `aindy_llm_tokens_total{provider="deepseek",model="deepseek-v4-pro"}` prompt 1233 + completion 969 = **2202**; `aindy_llm_calls_total{attributed="run",provider="deepseek"} 1` — the reading the 2.13.0 note said only appeared on `agent_flow`; tenant window `aindy:rm:tenant:<test>:tokens` = **5238** = planner 2636+400 + 2202, to the token; `score.computed.dimensions.llm_tokens: 2202` (every prior run: 0) |

The FR-35 consequence the handoff flags — *the governor's tenant window now moves on this
backend* — is real and inert here: `AINDY_QUOTA_MAX_TENANT_TOKENS` is unset. Set it and it will
count tool steps it never saw before.

---

## 4. Consumer-visible edges, checked against our source — none fire

| Change | Where we would feel it | Our source |
|---|---|---|
| `failure_class` on every `execute_tool` refusal and syscall **error** envelope (#703); cancelled / no-token / crashed-check attempted once, not three times | a reader keyed on envelope shape; a retry count in a test | additive; our checks are `!= "success"`. The failed run's `arm.analyze` was attempted once (one log line). `RETRY-CLASSIFY-1` is the runtime's own id — the worker seam had been dropping the class; not ours to close |
| A verify-failed run's unit finalises `failed`; no `[EU] invalid transition completed→completed` on completed `nodus_vm` runs (#713) | log noise we had called noise; unit counts | 0 `invalid transition` since boot across two runs. **1 past failed run's unit is still `executing`** (of 7 failed) — the un-backfilled case the handoff names; harmless, and it is what `execution_units group by status` will show anyone who counts |
| `user.id` on `syscall.*` spans deprecated for `enduser.id`; **removed next release** (#706); `chat` / `execute_tool` / `invoke_agent` span kinds | a trace exporter or query | no `OTEL_EXPORTER_OTLP_ENDPOINT` anywhere in compose, `.env.example` or the operations docs; every `user.id` in `apps/` is Python attribute access. Nothing to repoint. Recorded so the removal is not a surprise |
| `background_task_leases.fence` (`LEASE-FENCE-1`, #705) | a leadership split — two api replicas | one replica; the one lease row reads `fence = 0`. Never fires here |
| `AINDY_SYSEVENT_RETENTION` (#704) | nothing until set | left unset — §5.3 |
| `AINDY_NODUS_LLM_LEDGER_MAX` (256) | a run with > 256 provider calls in its tool steps | ours make one or two |

**Not touched:** the pipeline envelope, `require_execution_unit`, `to_envelope`, `run_flow`,
every route path and status code we consume. App-profile syscall count **97** = 23 runtime + 74
ours, unchanged.

---

## 5. Decisions recorded, and the two asks

### 5.1 Ask 1 — `args_schema` on our 15 tools: **taken, the PR after the adoption**

One kwarg per `register_tool` in the dispatcher's dialect (`required` + `properties[].type`,
property `description` for the planner — the validator ignores it), across the seven
`apps/*/agents/tools.py` modules; the `Args: {…}` prose removed from every description (two
contracts drift); the run-tool provider carries `args_schema` in its dicts. **Not passed as a
per-tool `input_schema`** the way the handoff phrases it: the Claude planner is one forced
`submit_plan` tool whose `steps[].args` is an open object, and fifteen per-tool schemas inside
it would need a `oneOf` branch per tool. The contract reaches the model as the runtime intends —
the catalog line in the system prompt renders `args={…}` per tool — and `submit_plan.args` now
says so in its description. `test_agent_tool_args_schema.py` (renamed from the prose guard) pins
the schema instead. `AINDY_TOOL_ARGS_VALIDATION` stays `warn`; flip after a stretch of
`aindy_tool_args_validation_total{outcome="invalid"}` reading zero live.

One dialect note: `_SCHEMA_TYPE_MAP["number"]` is `float` only, so `estimated_hours: 2` from a
planner would read `invalid` under `enforce`; `task.create` leaves that property untyped.
Recorded under FR-33 in the register; `(int, float)` minus `bool` would let it be typed.

### 5.2 Ask 2 — observe the first `leadgen.act` denial: **already on file, FR-38**

The handoff asks for the token-expiry recipe on a non-production profile. That was done on
2026-09-16 and recorded under FR-38 in the register, with one refinement the handoff should carry
forward: an *expired* token is not the gate's case (it fails at the run-level `execute_flow` check
before any step, by design); the denial the gate parks on is a token minted under a capability
ceiling that excludes `external_api_call`. Observed on both backends, one run each: on
**`nodus_vm`** (this app's default) the step fails at `tool_registry.py:816` and never negotiates;
on **`agent_flow`** the run parks `waiting` with `wait_state.authority_gate {decisions: [skip,
abort]}`, the operator's `skip` resume woke it from a different process, the step recorded
`skipped`, the run completed with `loop_enforced: true`. The flip waits on the `nodus_vm` seam —
FR-38 — not on more evidence from here. (#703's "once, not three times" would change the ×3
`capability.denied` in that record; not re-manufactured for this pass.)

### 5.3 `AINDY_SYSEVENT_RETENTION` — left unset; `report` first is the owner's call

`system_events` holds **89,743 rows**; the top two types are the runtime's
`watchdog.scan.completed` (27,718) and `autonomy.decision` (25,483). Our registered event types
(`analytics.score_updated`, `execution.completed`, `masterplan.goal_state_changed`, the reasoning
set) are unclassified → kept regardless. `report` deletes nothing and logs per-type counts —
that reading is worth one boot with it set, before anyone decides on `prune`, and it belongs with
`HEALTH-EVENT-VOLUME-1` / FR-18. `aindy_system_events_unclassified_rows` reads 0 today because
the job that computes it is not scheduled, not because nothing is unclassified.

### 5.4 The rest, at defaults

`AINDY_TOOL_ARGS_VALIDATION=warn` (nothing to validate until §5.1); `AINDY_NODUS_LLM_LEDGER_MAX`
256; `AINDY_BOOTSTRAP_RECONCILE` stays off — §6.2 is the argument for keeping it a decision.

---

## 6. Verification

### 6.1 Dev venv, 2026-09-17

```
venv imports 2.20.0 from site-packages (path printed)               — §1
test_runtime_dependency_contract.py                                 — 6 passed
test_memory_execute_no_recalc.py (rewritten, §2)                    — 5 passed
app-profile subset (seven CLAUDE.md files, -m app_profile)          — 55 passed
boot smoke: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16; 97 syscalls
full tests/unit                                                     — 1309 passed, 1 skipped, exit 0
ruff check apps/ tests/ — clean;  check_app_imports.py — 37 declared, 0 undeclared
```

### 6.2 ★ The exit-3 path, proven — image `7546a7aba3b6`, 2026-09-17 03:56–03:59 UTC

Stack was down (previous session). Pin bump → `build api` → `Successfully installed …
aindy_runtime-2.20.0` → `up -d --profile full --profile mail` with `AINDY_BOOTSTRAP_RECONCILE`
unset (compose default `false`).

```
[entrypoint] runtime schema: aindy-runtime bootstrap-schema
error: runtime-owned schema is not ready: Runtime-owned schema requires an explicit additive reconcile:
  Runtime table 'background_task_leases' is missing required column 'fence'.
Re-run with --reconcile to apply the additive column/index changes. This is safe to automate in an entrypoint: it adds, never drops.
state=upgrade_required operator_action=startup_reconcile exit_code=3
[entrypoint] bootstrap-schema exit 3: an ADDITIVE reconcile is required.
[entrypoint] This is the safe-to-automate case — columns/indexes are added, never dropped.
[entrypoint] Either set AINDY_BOOTSTRAP_RECONCILE=1 and restart, or apply it out-of-band:
[entrypoint]   docker compose run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile
```

`docker ps`: `Restarting (3)` — the container in its restart loop, printing exactly that, nine
times, touching nothing. Before: `alembic_version_runtime = 0018`, six columns on
`background_task_leases`. The out-of-band command the entrypoint prints, run verbatim:

```
ok: reconciled runtime-owned tables to packaged metadata.
ok: stamped alembic_version_runtime to revision 0019.        (exit 0)
```

After: `0019`; `fence | bigint | '0'::bigint | NOT NULL`; the one existing lease row reads
`fence = 0`. The api's next restart attempt passed the check and was `healthy` 42 s later. **The
exit-3 branch, the message, the out-of-band command and the restart policy all did what the
entrypoint comment says they do** — first time observed, ~3 minutes end to end, nothing dropped.
This is the case for keeping `AINDY_BOOTSTRAP_RECONCILE` off: a schema change arrived as a
decision with a paper trail, at the cost of one `docker compose run`.

### 6.3 Handoff §6, each read rather than assumed

| §6 check | Result |
|---|---|
| 1. version + path, in the container | `2.20.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| 2. `bootstrap-schema` after reconcile; contract | exit 0 — `runtime-owned tables already present`, `stamped 0019`; `SCHEMA_CONTRACT_VERSION 2026-09-16` |
| 3. ★ FR-35 live (run `e03f7af9…`, below) | `aindy_llm_tokens_total{provider="deepseek"}` 1233 + 969; `aindy_llm_calls_total{attributed="run"}` **1**; `score.computed.dimensions.llm_tokens` **2202**; tenant window 5238 = every token metered |
| 4. FR-34 on a failing run (run `1fd55459…`, below) | `failed`, `steps_completed 0 / steps_total 2 / current_step 1`; `score.computed` `{llm_tokens: 0, steps_completed: 0, steps_total: 2}`, score 0.0 |
| 5. FR-36 | `user_id is required` since boot: **0**; run 1 `loop_enforced: true`, `next_action: review_plan`, `next_action.chosen` event |
| 6. #713 | `invalid transition completed`: **0** across a completed and a failed `nodus_vm` run; run 1's `agent_run` unit `completed`, run 2's `failed`, both with `completed_at` |
| 7. readiness | `/health/deep` `syscall_registry {status: ok, count: 97, minimum_expected: 23}`, `healthy` |
| boot log at WARNING, redis present | the usual seven (`APP_DEPENDS_ON` gap ×2 twice, `STRIPE_WEBHOOK_SECRET` twice, `MAX_CONCURRENT_PER_USER=0`) **plus one**: `[job_recovery] re-dispatched 2 orphaned thread-mode job(s) at startup` — two `memory.generate_embedding` jobs from 02:26 and 02:28 UTC, orphaned by last night's teardown, both `success` at 03:59:18. Recovery doing its job. 0 ERROR / Traceback |
| container | `memory.peak` 506 MiB under `memory.max` 1536 MiB (boot + two runs + a warm worker); 0 postgres reinits; api restart count 9, all of them §6.2 |

**The two runs**, test account (`kingknight845@gmail.com`, token minted in-container), approved
by hand:

| run | goal | outcome |
|---|---|---|
| `e03f7af9…` 04:02:02–04:02:42 UTC | the 2.19.0 §6 objective — *Analyze `apps/arm/agents/tools.py` with ARM and summarise it in one sentence* | plan `arm.analyze {file_path} → memory.write` (right key, first try, from the `Args:` prose); **`completed 2/2` in 35 s**; ARM architecture 8, integrity 5, a real summary, `analysis_results` row; `memory.write` node `81151c4b…` written and embedded |
| `1fd55459…` 04:04 UTC | the same with `does_not_exist.py` — manufactured for §6 step 4 | plan `arm.analyze → memory.write`; step 0 `404: File not found`, attempted once; run `failed`, counters as in the table |

Both plans came from the Claude planner (`claude-opus-4-8`, 2636 + 400 tokens for run 1,
`attributed="unit"`).

### 6.4 FR-32 in the running image

Probe with `PYTHONPATH=/app`, `import AINDY.main` then `_register_flow_engine()` (the 2.20.0
order): **113 flows**; `memory_execute_loop = {start: memory_execution_validate, edges:
{validate: [run]}, end: [memory_execution_run]}`; `memory_execution` identical;
`memory_execution_orchestrate in NODE_REGISTRY` → **False**;
`register_default_memory_execute_loop()` → **False**. Tools: 15, `args_schema` on none.

---

## 7. Found on the way

### 7.1 The planner has never seen the Infinity context — `AGENT-PLANNER-CONTEXT-BOUNDARY-1` (ours) + FR-39 (theirs)

Reading run 1's log at WARNING, twice under the planner's trace:

```
get_user_kpi_snapshot failed for {'_redacted_type': 'UUID'}: 'NoneType' object has no attribute 'query'
```

`apps/agent/agents/runtime_extensions.py::build_planner_context` — our
`register_planner_context_provider("default", …)` — reads `db` and `user_id` from the context the
runtime hands it. The runtime routes that call through the extension boundary
(`registry.get_planner_context` → `_sanitized_extension_input`), which **drops `db` at the root by
design** and redacts the `uuid.UUID` that `agents/agent_runtime/shared.py:81` passes as
`user_id`. So the provider has had `db=None` and an unusable tenant on every invocation since the
boundary landed (2026-05-20), the KPI block, the reasoning-recommendation block and the memory
enrichment all took their `except: return ""` path, and the planner's system prompt has been the
base prompt plus the tool catalog — nothing of the user. Every plan to date was made blind to
the Infinity score it is supposed to steer by. The provider's `system_prompt` *is* what reaches
the model (`planning.py:173-176`, `planner_anthropic.py:159`), so this is not a cosmetic gap.

Pre-existing, not 2.20.0's; visible now because a run's log was grepped at WARNING for FR-36.
**Same family as `INFINITY-COMPLETION-HOOK-BOUNDARY-1` and `AGENT-COMPLETION-HOOK-USERID-1`**,
one hook over — and it is exactly the case FR-36's second ask named: a redacted *documented
primitive* is the boundary hiding a bug. 2.20.0's fix (#708) stringifies `user_id` at the
completion-hook builder and adds a boundary test for **that builder's** keys; `shared.py:81`
(planner context) and `:90` (tools-for-run) still pass `_db_user_id(user_id)`, a `uuid.UUID`.

Two halves:

- **Ours** — the provider must open its own session (as `handle_agent_run_completed` does) and
  take the tenant through `_hook_user_id`, which already treats a redacted dict as absent. With
  that, the blocks build the moment a real string arrives. Filed `AGENT-PLANNER-CONTEXT-BOUNDARY-1`
  in `TECH_DEBT.md`; the fix is the next PR.
- **Theirs — FR-39**: `str()` at the two remaining `shared.py` sites, and widen #708's test from
  the completion-hook builder to every hook context the runtime builds. Until it lands our fix
  has nothing to identify the user by: there is no `run_id` to re-fetch at planning time.

`get_tools_for_run` (our other provider) ignores its context, so tool selection was never
affected — which is why the runs above still chose the right tools.

### 7.2 One `memory.generate_embedding` job `pending` with `attempt_count 0`

Created 04:02:42 by the runtime's feedback capture (`feedback.latency_spike` → memory node
`932ffdb6…`, *"Latency spike detected at 34977.0ms"*). The node **already has its embedding**;
the job never dispatched and is still `pending` twenty minutes on. Runtime-side, cosmetic (the
node is searchable), and it will be one of `job_recovery`'s "orphaned thread-mode jobs" at the
next boot. Noted, not filed: one occurrence.
