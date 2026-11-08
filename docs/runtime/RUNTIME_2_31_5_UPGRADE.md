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

## 5. Rebuild: done 2026-11-08, **live on 2.31.5 since 00:57:50Z**

**We are on 2.31.5.** This is the report the runtime's advisory for 2.31.4's fixes waits for (handoff §4). The
image was built from `main` at `4ca3353` (#553). It carries everything the 2.31.4 image did (the app's
route-sweep fixes #545 and #547 to #550), plus the 2.31.4 rebuild record (#552).

1. **Identity counter, window 16** (2026-11-08 00:29:36Z → 00:53Z): no samples, so 0 refused, over **0**
   syscall outcomes. It ran 23 minutes with no traffic. The recreate opened **window 17**.
2. **Built** image `9cba83fc2392` and checked it before the recreate: `2.31.5 5.15.1` from site-packages,
   `apps/_shared/egress.py` present, 4 `.nd` files packaged.
3. **Recreated at 00:57:50Z** with both compose files and both profiles. Healthy in about 90 s, 0 restarts,
   port still `127.0.0.1:8000`.
4. **The handoff's check:** `2.31.5 5.15.1 ['/usr/local/lib/python3.11/site-packages/AINDY']` (ask 1).
   `/api/version`: `default-apps`, 16 plugins. `/health` 200. Schema heads unchanged: runtime `0020`, app
   `fl1metrics0001`. 0 `ERROR` or traceback lines at boot. 0 `executing` agent runs. `NODUS_RUN_STATE_ROOT`
   is still `/var/lib/aindy/nodus-state`.
5. **2.31.5's change, live** (designated test account, read-only):
   - `GET /apps/agent/runs/{id}` on one of the owner's runs answers **404**, the same as a made-up run id.
   - The 2.31.4-image checks still hold: an event naming another user's drop point answers 404, and a
     retired legacy route answers 404 with the shared key.
6. `aindy_effect_gate_outcomes_total` has no samples yet, as expected right after a restart.

**Still owed, after a day of normal traffic (from about 2026-11-09 01:00Z):**

- `tenant_mismatch` from `/metrics` (ask 4). It should read 0.
- `aindy_payload_identity_mismatch_total` by `syscall`, and the 2.31.3 record's §7 log lines. This read has
  carried over from 2.31.3, whose windows 13 to 16 were all too short or quiet to count.
