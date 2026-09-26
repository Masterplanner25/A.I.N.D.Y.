---
title: "Runtime 2.24.0 + ui-kit 2.1.1 upgrade — adoption"
last_verified: "2026-09-26"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.24.0 + ui-kit 2.1.1 upgrade — adoption

Floor `>=2.23.0,<3.0` → `>=2.24.0,<3.0`; build pin `==2.23.0` → `==2.24.0`; `@aindy/ui-kit`
`^2.1.0` → `^2.1.1`. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.24.0.md`.

**This release answered all five open FRs: FR-43 … FR-47.** FR-44 is verified live (§3). FR-46
ships default-off, and its evidence run is owed (§5). No migration.

---

## 1. Installed, printing the path

```
2.24.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # dev venv, pip install -c constraints.txt
2.24.0 ['/usr/local/lib/python3.11/site-packages/AINDY']                     # container
@aindy/ui-kit 2.1.1                                                          # client/node_modules (npm ci from the lock)
```

Boot: `default-apps`, 16 plugins, `/health` 200.

## 2. Schema: FR-43 on a stack we had already fixed

`bootstrap-schema` now compares string length and numeric precision. We widened
`system_events.source` to 128 out of band on 2.22.0 (`RUNTIME_2_22_0_UPGRADE.md` §2), so as the
handoff predicted our entrypoint saw exit 0. Read from the database: `alembic_version_runtime`
**`0020`**, `system_events.source` **128**.

## 3. FR-44: verified live (handoff §8 ask 2)

This is the 09-23 setup that stranded the run until a restart. The api had booted **before** the
park; the park was made in a separate `docker exec` (`leadgen.act` under a token that excludes
`external_api_call`, test account); the resume went over HTTP through our route. Run
`3880d88e-c95c-4a7c-8a0b-9743ef7e64e6`:

```
POST /apps/agent/runs/{id}/resume {"decision":"skip", …}
→ 200 | waiters_notified: 1 | authority_gate.run_status: "resuming"
→ run completed at the first poll, no restart; step 0 skipped; wait_state cleared
```

We have no client surface that reads `run_status`, so the new `"waiting"` value (§2 of the
handoff) needs no branch here.

## 4. FR-45 and FR-47: the client

- **FR-47 (ui-kit 2.1.1):** `createAgentRun` passes `timeoutMs: 90_000` and the #410
  poll-on-408 workaround is removed. A 408 now means the kit's own 90 s timer fired. Run creation
  still has no idempotency key (handoff §6 note 1), so that error tells the user the run may still
  arrive rather than inviting a resubmit. We use no caller `signal`, so the `AbortError` change does
  not reach us.
- **FR-45:** the runtime's envelope adapters stamp `X-AINDY-Envelope` themselves, including on
  error statuses whose body carries `data`. This is harmless, because the kit throws on any non-2xx
  first. Our `apps/_shared/envelope.py::stamped` stays: it is a no-op over the runtime's adapters
  and the only stamp for our own `social_feed_response_adapter`. The guard test
  (`test_response_adapters_stamp_envelopes.py`) holds either way. The one test that had pinned
  error-status behaviour *through* the runtime's adapter now pins our wrapper alone.
- The ui-kit lock entry was edited by hand (only its version, URL and integrity change; 2.1.1's
  dependencies are identical), as for 2.1.0, so npm on Windows does not drop the `wasm32`
  optional packages from the lock.

## 5. FR-46: step references, default off

- **The planner rule follows the flag.** #412's rule told the planner *"a step cannot read an
  earlier step's result"*. With `AINDY_PLAN_STEP_REFERENCES=1` the runtime's catalog teaches the
  `$from_step` form, and that rule would contradict it. `planner_system_prompt()` now uses the
  runtime's own `step_references_enabled()` to pick the matching rule, so the two cannot
  disagree. With the flag off, nothing changes.
- **The 2 KB cut is ours, and it is fixed** (handoff ask 4). `sys.v1.research.query` returned
  `raw[:2000]`, which dated from the initial extraction and cut mid-word with no marker. It now
  returns up to **6000** characters (the findings-digest cap), cut at a word boundary and marked
  ` … [truncated]` (`apps/search/syscalls.py::_research_excerpt`, `test_research_excerpt.py`).
  `search_service.raw_excerpt` is the Search page's preview, not an agent input; it is unchanged.
- **Owed: the evidence run** (handoff §8 ask 1). Turn the flag on and re-run the owner's goal. The
  pass condition is that the `memory.write` step stores step 0's findings.

## 6. IDEM-14, nodus-lang 5.15.0

- **IDEM-14** (tool idempotency key per plan step): we have no `EXACTLY_ONCE` tool, and none of
  our tests stubs `execute_tool` with a fixed signature. The unit suite passes on 2.24.0.
- **nodus-lang 5.15.0:** we do not pin it, so nothing to move.

## 7. Operational note

`npm ci` on Windows fails with `EPERM` on `lightningcss-win32-x64-msvc` while Vite is running,
because the dev server holds the native module open. It also deletes `node_modules` first, so Vite
breaks until the install finishes. Stop Vite, install, then restart it detached.
