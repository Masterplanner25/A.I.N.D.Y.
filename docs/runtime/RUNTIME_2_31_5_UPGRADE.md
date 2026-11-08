---
title: "Runtime 2.31.5 adoption"
last_verified: "2026-11-08"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.31.5 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.31.5.md` (tag `v2.31.5`, `671202a`, #914). We come from
2.31.4, which went live at 2026-11-08 00:29:36Z (`RUNTIME_2_31_4_UPGRADE.md` §6). No schema change (head
stays `0020`, contract `2026-09-20`), no env var, no API-key scope, no ui-kit release (2.1.1 stays). The one
dependency change is **nodus-lang 5.15.1**, which arrives through the runtime's pin.

**A security release.**

Pin: `constraints.txt` `aindy-runtime==2.31.5`, floor `>=2.31.5,<3.0`, moved together
(`test_runtime_dependency_contract.py`). We do not pin `nodus-lang` ourselves.

## 1. nodus-lang 5.15.1: run-state path traversal (#913)

`resume_workflow("../x")` from a guest script could read or delete a `.json` outside nodus's run-state
directory. 5.15.1 validates every run-state id.

**Ours:** `docker-compose.prod.yml` sets `NODUS_RUN_STATE_ROOT: /var/lib/aindy/nodus-state` on the api, which
runs Nodus, so the reachable files were the ones on the `nodus_state` volume. The variable stays set.

## 2. Someone else's agent run answers 404, like a missing one (#912, DEC-118)

**Ours:** `GET /apps/agent/runs/{id}` goes through `get_agent_run_runtime`, so it now answers 404 for another
user's run. No test asserts 403 there. No client or app code treats a 403 from agent runs specially; the only
special 403 handling in the client is the change-password dialog.

## 3. The effect ledger checks a slot's tenant (#912, DEC-118)

`aindy_effect_gate_outcomes_total{outcome="tenant_mismatch"}` should always read 0. The metric is already
exported by the running api. The read after a day of traffic is owed (§5).

## 4. Tests on 2.31.5, and 2.31.4's asks against this version

The local venv was reinstalled with `-e .[test] -c constraints.txt`. It reads
`2.31.5 5.15.1 ['…\venv\Lib\site-packages\AINDY']`.

Full `pytest tests -m app_profile` on 2.31.5: **1,823 passed, 292 skipped, 0 failed**. The log has **0**
`TENANT_VIOLATION` and **0** `tenant_mismatch`, and no failure reports an unexpected 404 (ask 2).

2.31.4's asks, re-checked against this version on 2026-11-08 (ask 3). The answers are the same as in
`RUNTIME_2_31_4_UPGRADE.md` §1 to §4:

- **Webhook subscriptions:** 0 active of 2, so nothing relies on other users' events.
- **`/client/error` and `/client/vitals`:** sent through `authRequest` with the bearer.
- **Watcher:** `watcher_signals` has 0 rows, so nobody runs a watcher and there is no key to rotate.
- **Nodus upload and flow ownership:** nothing of ours calls those routes.

## 5. Rebuild: owed

After merge: read identity window 16 (opened at the 2.31.4 recreate, 2026-11-08 00:29:36Z), rebuild the api
image, recreate, and run the handoff's check:

```bash
docker exec <api-container> python -c "import AINDY, AINDY._version as v, importlib.metadata as m; print(v.__version__, m.version('nodus-lang'), list(AINDY.__path__))"
# expect: 2.31.5 5.15.1 ['/usr/local/lib/python3.11/site-packages/AINDY']
```

Then record it here. The runtime's advisory for 2.31.4's fixes waits for that.

**After a day of normal traffic (ask 4):** `tenant_mismatch` from `/metrics`, together with the identity
read carried from 2.31.3 and 2.31.4.
