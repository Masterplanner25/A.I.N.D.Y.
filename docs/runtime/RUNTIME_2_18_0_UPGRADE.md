---
title: "Runtime 2.18.0 upgrade — adoption"
last_verified: "2026-09-16"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.18.0 upgrade — adoption

Floor moved `>=2.17.0,<3.0` → `>=2.18.0,<3.0`; build pin `==2.17.0` → `==2.18.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.18.0.md`.

**This release closes our FR-31** — filed 2026-09-16 from the 2.17.0 container verification
(`RUNTIME_2_17_0_UPGRADE.md` §5), fixed upstream the same day (#686–#689).

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `SCHEMA_CONTRACT_VERSION` unchanged at `2026-09-10`;
`git diff v2.17.0..v2.18.0 -- AINDY/db/models AINDY/memory/memory_persistence.py` is empty. The
diff under `AINDY/` is 16 files (+351 / −883, most of the removal being `nodus_builtins.py`).
**One module we import from changed:** `runtime/nodus_execution_service.py` — additive (two new
functions, `ensure_runtime_flows_registered`, `resolve_resumable_flow`); our
`execute_nodus_task_payload` (`apps/memory/bootstrap.py:66`) is untouched. The two removed
symbols (`AINDY.runtime.nodus_builtins.*`, `nodus_worker.WorkerWaitSignal`) → 0 hits in `apps/`,
`tests/`, `client/src`.

---

## 1. The dev venv, re-checked printing the path

```
2.17.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.18.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -c constraints.txt --no-cache-dir
```

---

## 2. Gained on adoption — FR-31 closed, all three asks

- **Ask 1 — `nodus_execute` registered at boot**, by `register_all_flows()` and by the FR-15
  worker's boot (which had never registered the runtime-owned flows at all). Both resume
  builders also resolve it on a miss.
- **Ask 2 — a skipped resume no longer consumes the registration.** A flow this process does
  not hold re-arms the wait under the run id; the WARNING now says the wait is re-registered.
- **Ask 3 — the route says whether anything was woken.** `resumed` now means *woken*; each
  `results` entry carries `woken: bool` (§3).
- **What the runtime found reading our filing:** `agent_execution` — the AGENT_FLOW backend's
  flow, the one *our* agent runs use — was never in `FLOW_REGISTRY` either, so an agent run
  parked by the 2.17.0 authority gate could not have survived a restart. It now resolves for
  resume only (`resolve_resumable_flow`), deliberately not registered publicly (a public entry
  would be startable through `sys.v1.flow.run` without an `execution_token`). **This makes the
  2.17.0 §3.3 ask — declaring one tool `on_denial="wait"` — safer to try than it was.**

The 2.17.0 workaround ("run a script first") is retired; §5 step 4 below is the handoff's
original order, unmodified.

---

## 3. Consumer-visible edges, checked against our source — none fire

| Change | Where we would feel it | Our source |
|---|---|---|
| `POST /platform/flows/runs/{id}/resume`: `resumed` means *woken*, each result carries `woken: bool`; nothing registered to wake → `200`, `payload_injected: true, woken: false, resumed: false` + WARNING, payload kept for the next rehydrated wake (#689) | a client keying on `resumed: true` to mean "stored" | nothing of ours calls the route (`flows/runs` → 0 hits; the two `getFlowRun` exports are read-only and uncalled). `Genesis.jsx`'s "resumed" is the session's own wording, not this field |
| Multi-instance thread-mode wait claimed from a dead instance is resumed (#686) | more than one api instance | we run one |
| A flow run completing with no `user_id` / `workflow_type` finalises its unit (#685) | `execution_units` counts | our route-started flows carry both |
| Boot log: `[rehydrate] … waiting EU(s)` lines gone; `wait_eus_rehydration_failed` retired | log shape | nothing of ours filters on it |

**Not touched:** the pipeline envelope, `require_execution_unit`, `to_envelope`, `register_tool`,
`run_flow`, every route path and status code we consume.

The removed guest namespaces (`event.wait()`, `memory.*` in nodus scripts) never worked on any
version; the wait is now `await_event("<event>", <schema or nil>)`, with the three state keys
still honoured. We run no waiting guest script; Tutorial 2's script sets the keys directly and
still works (§5).

---

## 4. The two 2.17.0 asks — unchanged, still owner's calls

`RUNTIME_2_17_0_UPGRADE.md` §3: named predicates behind a drain (#680); one tool declaring
`on_denial="wait"` (#681) — now with the restart-survival gap closed.

---

## 5. Verification

### Dev venv, 2026-09-16

```
venv imports 2.18.0 from site-packages (path printed)               — §1
test_runtime_dependency_contract.py                                 — 6 passed
app-profile subset (seven CLAUDE.md files, -m app_profile)          — 55 passed
boot smoke: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16; 98 syscalls
ruff check apps/ tests/ — clean;  check_app_imports.py — 37 declared, 0 undeclared
```

**Full `tests/unit` on the installed 2.18.0 (2026-09-16, this venv, path printed):** `1249 passed, 1 skipped, exit 0` — read from the summary line of the log file.

### Container rebuilt and verified (2026-09-16 15:54 UTC, same session)

Order, because §4 step 4 requires a run parked on the *old* release: stack up on the 2.17.0 image →
Tutorial 2 Steps 1–3 → run `eb23edda…` parked, signature `77c1d6de…`, `dead_letter` 0 → stack
down → pin bump → `docker compose … build api` → image `d02181cdf2ac`, `Successfully installed …
aindy-runtime-2.18.0` → stack up, `healthy`. Handoff §4, each read rather than assumed:

| §4 check | Result |
|---|---|
| 1. version + path, in the container | `2.18.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| 2. `bootstrap-schema` | exit 0 |
| 3. retired boot lines (`[rehydrate] Found` / `WAIT rehydration registered`) | **0**; nothing new at WARNING (the eight at boot are the usual `APP_DEPENDS_ON` ×2, `STRIPE_WEBHOOK_SECRET`, `MAX_CONCURRENT_PER_USER`, `job_recovery`) |
| 4. ★ **FR-31 live, the original order** — the run parked on 2.17.0, resumed **first**, before any script ran in the new process | **passes.** After boot: `waiting`, signature unchanged, `waiting_flow_runs` row present. Resume → `resumed: True`, `results: [{payload_injected: True, woken: True}]` → `success` within seconds, `nodus_received_events` carries the payload, `outcome: approved`. `not in FLOW_REGISTRY` lines: **0**. `dead_letter`: 0. On 2.17.0 this exact sequence left the run orphaned |
| 5. the `woken: false` shape | skipped, as the handoff allows — it needs a `waiting` row with no scheduler entry, which only a fresh boot produces for about a second; the runtime's unit test pins it |

Test account promoted to `is_admin` for the park and the resume, reverted each time. The
2.17.0 "run a script first" workaround is retired from our notes; `RUNTIME_2_17_0_UPGRADE.md` §5
stays as the record of what it was.

