---
title: "Runtime 2.17.0 upgrade — adoption"
last_verified: "2026-09-16"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.17.0 upgrade — adoption

Floor moved `>=2.16.0,<3.0` → `>=2.17.0,<3.0`; build pin `==2.16.0` → `==2.17.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.17.0.md`.

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `SCHEMA_CONTRACT_VERSION` unchanged at `2026-09-10`;
`git diff v2.16.0..v2.17.0 -- AINDY/db/models AINDY/memory/memory_persistence.py` is empty. The
diff under `AINDY/` is 27 files (+1038 / −378) — six runtime-side backlog items, one of them a
removal. Modules we import from that changed, and what we take from them:

| Module we import | What changed | Our symbols |
|---|---|---|
| `core/execution_gate.py` | **`ExecutionWaitSignal` removed** (§1); −96 lines | `require_execution_unit` (2 sites), `to_envelope` (20 sites) — both still defined, unchanged. **We never imported the removed name** (`grep -rn ExecutionWaitSignal apps/ tests/ client/src` → 0) |
| `agents/tool_registry.py` | `register_tool` gains `on_denial=` (additive; the `def` line itself is not in the diff) | `register_tool` (15 call sites — the handoff counts 22; the difference is loop-registered tools), `TOOL_REGISTRY`, `register_tool_suggestion` — unchanged |
| `kernel/syscall_dispatcher.py` | +32: cancellation refusal before a handler runs (§2 row 3); no `def`/`class` line changed | `dispatch_syscall`, `get_dispatcher`, `make_syscall_ctx_*`, `child_context`, `SyscallContext` — unchanged |
| `runtime/flow_engine/__init__.py` | exports `register_predicate`, `DEFAULT_PREDICATE`, `PREDICATE_REGISTRY`, `UnknownPredicate`, `PredicateRegistrationError` (§3.1) | `run_flow` — unchanged |

One precision on the handoff: it says our only `execution_gate` imports are `to_envelope` in
"three routers". It is `to_envelope` at 20 sites and `require_execution_unit` at 2; the point —
none of them is the removed symbol — holds.

---

## 1. The dev venv, re-checked printing the path

```
2.16.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.17.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -c constraints.txt --no-cache-dir
```

---

## 2. Unflagged behaviour changes on paths we use — checked against our source

| Change | Where we would feel it | Our source |
|---|---|---|
| `POST /platform/flows/runs/{id}/resume` no longer fails to wake a run whose payload carries a client `correlation_id` key (#678) — before, `resumed: true` on the wire and the run parked forever | any resume with that key in the payload | our `POST /apps/agent/runs/{run_id}/resume` (`agent_router.py:249`) is the *agent* resume (`resume_agent_run_runtime` → `publish_event`), not this route. Nothing of ours calls the flow-runs resume (`flows/runs` → 0 hits; the two `getFlowRun` exports are read-only and uncalled). Checked live anyway — §5 step 6 |
| The same route can answer **422** when the waiting node declared a `resume_schema` (#677) | only a run whose flow/script opted in | `resume_schema` / `nodus_wait_resume_schema` → **0 hits** in `apps/`; nothing of ours can produce it. Our routers already branch on `!= "success"` |
| A cancelled agent run stops sooner (#682): the next syscall is refused before its handler; an *isolated* tool's worker is killed | `ExecutionConsole` may show more refused effects / fewer completed steps on cancelled runs; `aindy_run_cancel_observed_total{surface}` gains `syscall`, `tool_worker` | `isolation=` → **0** of our tools declare it, so the worker-kill half cannot fire; the syscall-refusal half applies to any run of ours that is cancelled — it is the intended mechanism, not a regression |

**Not touched:** the pipeline envelope shape, `require_execution_unit`, `to_envelope`, every
route path and status code we consume today.

---

## 3. Opt-ins and the two asks — recorded, not taken (owner's calls)

Both asks change something with a cost that is the owner's to weigh, so this adoption records
them and stops. Neither is required for the pin to move.

### 3.1 Named flow predicates (#680) — ask: migrate our seven lambdas

`{"target": …, "when": "<name>"}` + `@register_predicate("<name>")`, replacing
`{"target": …, "condition": <lambda>}`. Named decisions enter the graph signature, so a predicate
renamed or rerouted between suspend and resume quarantines the suspended run instead of resuming
it into a decision it was never planned for — the blind spot `FLOW-GRAPH-SIGNATURE-1` documents.

**Our seven, re-derived** (`grep -rn '"condition": lambda' apps/` → exactly 7):
`automation/flows/flow_definitions.py:723` (a multi-line condition),
`automation/flows/watcher_flows.py:160,164,168` and `tasks/flows/tasks_flows.py:465,469,473` —
the last two files are the same `watcher_decision` switch twice: `== "execute"`, `== "defer"`,
`lambda s: True` (the built-in `"default"`).

**★ The cost:** converting an edge from `condition` to `when` changes that flow's graph signature
**once**, so any run parked on that flow at deploy time is quarantined (dead-lettered with a
reason). The migration is: drain that flow's parked runs, deploy, done — per flow. Every existing
flow's digest is byte-for-byte unchanged by the upgrade itself (§5 step 4 measures exactly that).
**Not done here** — a signature change with a drain window is a deploy decision, not an adoption
step. When it is taken: three `register_predicate` names (`watcher_execute`, `watcher_defer`, and
whatever `:723` decides), the shared `watcher_decision` switch done once and used twice.

### 3.2 Typed wait payloads (#677) — optional, no ask

A WAIT node may declare `resume_schema`; a bad resume is refused 422 before anything is injected.
Adoption is visible on `aindy_flow_resume_payload_total{outcome}` — `untyped` is every wait we
have, which is one (`genesis_track_message`). Nothing to do until we want the refusal.

### 3.3 The authority WAIT gate (#681) — ask: declare one tool, so phase 3 has evidence

`register_tool(..., on_denial="wait")`: a tool refused for lack of authority parks the agent run
(`AgentRun.status = "waiting"`, `wait_state {event_type, flow_run_id, authority_gate}`) instead of
failing it; an operator resumes with `{"decision": "skip" | "abort"}` on
`POST /platform/flows/runs/{wait_state.flow_run_id}/resume`. No `grant` — the gate cannot widen
authority. Behind `AINDY_AUTHORITY_NEGOTIATION` (default off, and off here).

**The ask:** `AUTHORITY-NEGOTIATION-1` phase 3 flips the default "once a real tool declares a
variant or a gate and a denial has been observed" — and **zero tools anywhere declare either,
including our 15**. The runtime asks us to pick one whose denial we would rather have parked than
failed (the ones that send or spend), declare it, turn the flag on in a non-production profile,
and report the first denial. **Not done here** — which tool, and turning a flag on, are the
owner's; the candidates by that criterion are the freelance/social tools that send or spend. Once
chosen it is one kwarg on one `register_tool` call plus the flag in `.env`.

**Taken 2026-09-16 (#378): `leadgen.act`, `on_denial="wait"`.** The owner's pick, by the
criterion above: since #369 it is the tool that emails a real person. Where a denial would
actually come from, read from `check_tool_capability` rather than assumed: the token is minted
*from the plan* at approval, so a granted plan rarely denies at execution — the realistic cases
are an **expired token** (24 h TTL; a run parked on an approval for a day, then resumed) and a
**delegated run's ceiling** excluding egress. In both, failing the step would discard the
`leadgen.search` work already done; parking keeps it and hands a human `skip | abort`. Plumbed
`AINDY_AUTHORITY_NEGOTIATION` through `docker-compose.prod.yml` (compose passes only declared
variables — the shadow-flag lesson) and documented it in `.env.example`; set `true` in the local
`.env` only. `test_leadgen_act_on_denial_wait.py` pins the declaration and that any further gate or
variant is added to its list on purpose, because each one is evidence the runtime reads.
**The first denial has not been observed yet** — that needs the flag live on a rebuilt image and
a denial, which on this stack means manufacturing the expiry case; recorded in
`RUNTIME_2_19_0_UPGRADE.md` §5 when done.

---

## 4. Optional cleanup — the ten `waiting` route units are now unreachable

With `ExecutionWaitSignal` gone, nothing can transition the ten FR-29 rows kept as evidence; the
handoff offers `update execution_units set status='failed' where status='waiting' and
source_type='route'`. **Not run** — the owner's standing decision (2026-09-15/16) is that the rows
stay. They cost nothing now (the rehydration guard from 2.16.0 skips them silently).

---

## 5. Verification

### Dev venv, 2026-09-16

```
venv imports 2.17.0 from site-packages (path printed)               — §1
test_runtime_dependency_contract.py                                 — 6 passed
app-profile subset (seven CLAUDE.md files, -m app_profile)          — 55 passed
boot smoke: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16; 98 syscalls
ruff check apps/ tests/ — clean;  check_app_imports.py — 37 declared, 0 undeclared
grep -rn ExecutionWaitSignal apps/ tests/ client/src               — 0 (handoff step 3)
```

**Full `tests/unit` on the installed 2.17.0 (2026-09-16, this venv, path printed):** `1240 passed, 1 skipped, 382 warnings, exit 0` — read from the summary line of the log file.

### Container rebuilt and verified (2026-09-16 06:39 UTC, same session)

Order mattered for §4 step 4, so: stack up on the 2.16.0 image (`f6d22e2ba5e1`) → Tutorial 2
Steps 1–3 → run `8c63136f…` parked, signature `77c1d6de…`, `dead_letter` 0 → stack down → pin
bump → `docker compose … build api` → image `206a1276d4fd`, `Successfully installed …
aindy-runtime-2.17.0` (pip step 13 s on a warm cache) → stack up on a **477 MB** host, `healthy`,
0 restarts. Handoff §4, each read rather than assumed:

| §4 check | Result |
|---|---|
| 1. version + path, in the container | `2.17.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| 2. `bootstrap-schema` | exit 0; heads runtime `0018`, app `ga1shadow0001` unchanged |
| 3. `grep -rn ExecutionWaitSignal apps/` | 0 (also `tests/`, `client/src`) |
| 4. ★ the run parked on 2.16.0, after the upgrade | **not quarantined**: `waiting`, `waiting_for=review.approved`, signature `77c1d6de…` unchanged, `dead_letter` still 0, `waiting_flow_runs` row present (rehydrated). **Its resume is the story below** |
| 5. retire the ten `waiting` route units | **not run** — the owner keeps them as evidence; they are unreachable and silent |
| 6. ★ #678 — resume with `correlation_id` in the payload | **holds, once the flow is registered** (below): `success`, `nodus_received_events` carries `{…, "correlation_id": "my-ref-3"}`, history `WAIT, SUCCESS` + `nodus_record_outcome` |
| boot health | 0 postgres reinits, 0 tracebacks, 0 job-storm lines, 0 `seed failed`, 0 quarantine lines; `/api/version` `default-apps` / 16 |
| FR-30 still holds on 2.17.0 | 37 post-upgrade route units, **all `completed`**, 0 `executing` |

#### Step 4/6 — what actually happened, and FR-31

The first resume of the pre-upgrade run answered `200 resumed: true, payload_injected: true` and
the run stayed `waiting` — #678's exact wire signature — with one WARNING:
`[flow_rehydrate] resume callback: flow='nodus_execute' not in FLOW_REGISTRY … skipping resume`.
`nodus_execute` is registered lazily, on the first script run of a process; after a restart nothing
has run, the rehydrated callback looks the flow up at wake time, finds nothing, and returns —
after the wake has consumed the registration. A second resume did nothing (no registration left).
Restart the api → run any script first → resume → **`success`**. Same run, signature, route and
payload; the only variable was whether a script had run in the process. Filed as
`RUNTIME_FEATURE_REQUESTS.md` **FR-31** — pre-existing (every earlier live run parked and resumed
inside one process lifetime, so rehydration of a Nodus wait had never been exercised), not a
2.17.0 change, and nothing of ours runs a waiting script today. **The handoff's step 4 as written
cannot pass on a fresh boot; the order that works is run-a-script-first.**

Test account promoted to `is_admin` for the tutorial steps and reverted each time. The two extra
runs the script-first steps parked (`9f753154…`, `85d77a7e…`) were resumed with `approved: false`
→ `rejected`; 0 runs left `waiting`. Test-account memory nodes accumulate one `pending/decision`
and one `insights/decision` per pass — harmless, noted.

