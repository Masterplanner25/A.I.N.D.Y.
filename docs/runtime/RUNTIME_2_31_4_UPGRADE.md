---
title: "Runtime 2.31.4 adoption"
last_verified: "2026-11-07"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.31.4 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.31.4.md` (tag `v2.31.4`, `9973b26`, #909). We come from
2.31.3 (live since 2026-11-07 08:14Z, `RUNTIME_2_31_3_UPGRADE.md`). No schema change (head stays `0020`,
contract `2026-09-20`), no dependency-pin change, no env var, no ui-kit release (2.1.1 stays).

**A security release.** It fixes the remaining runtime-audit findings that needed a scoped API key to
reach, and adds per-user watcher keys. The same day, the app shipped its own route-sweep fixes (#545,
#547 to #550), so one image rebuild carries both.

Pin: `constraints.txt` `aindy-runtime==2.31.4`, floor `>=2.31.4,<3.0`, moved together
(`test_runtime_dependency_contract.py`).

## 1. Webhooks answer to their creator (#907, DEC-116)

A subscription now gets only its creator's events, unless the creator is an admin at delivery.

**Ours:** two rows in `webhook_subscriptions`. Both are `task.completed` with owner class `first-party-app`,
created 2026-08-01 by one non-admin user, and **both are inactive**. So nothing of ours relied on other
users' events, and nothing loses events (ask 3).

## 2. Script and workflow names have owners (#907, DEC-116)

`POST /platform/nodus/upload` with `overwrite`, and `POST /platform/nodus/flow` on a name someone else
holds, now answer 403.

**Ours:** no app, client or script code calls either route. Our four `.nd` workflows register at boot
through `register_nodus_workflow` (`apps/_shared/nodus.py`), which this release leaves unchanged.

## 3. `/client/error` and `/client/vitals` take their owner from the session (#907)

**Ours:** the client sends both through ui-kit's `authRequest` (`client/src/api/operator.js`
`reportClientError`, `reportClientVitals`), which attaches the bearer token. A signed-in report keeps its
owner (ask 4). An unsigned report is still accepted, with no owner.

## 4. Per-user watcher keys (#908, DEC-117)

`/watcher/keys` mints a user's own key with scope `watcher.signals`. With it, signals belong to the key's
owner, and naming anyone else answers `TENANT_VIOLATION`. `X-API-Key` still names any user, so it is for
services only.

**Ours:** `watcher_signals` has **0 rows**. Nobody runs a watcher against this stack with any key, so no
machine holds `AINDY_API_KEY` for one and there is nothing to rotate (ask 5). The app's 11-07 route sweep
had flagged the watcher routes acting as any user under the shared key. This release answers that, so it
was never filed (see `RUNTIME_FEATURE_REQUESTS.md`, *Open as of 2026-11-07*).

## 5. Tests on 2.31.4

The local venv had drifted to **2.28.0** under the 2.31.3 pin, so it was reinstalled with
`-e .[test] -c constraints.txt`. `import AINDY._version` now reads 2.31.4 from site-packages.

Full `pytest tests -m app_profile` on 2.31.4: **1,823 passed, 292 skipped, 0 failed**. The log has **0**
`TENANT_VIOLATION`, **0** `script_not_owned` or `workflow_not_owned`, and no 403 (ask 2).

## 6. Rebuild: done 2026-11-08, **live on 2.31.4 since 00:29:36Z**

**We are on 2.31.4** (handoff §6: the advisory waits for this). The image was built from `main` at
`908573b` (#551) and also carries the app's route-sweep fixes, #545 and #547 to #550.

1. **Identity counter, window 15** (2026-11-07 21:52:53Z → 2026-11-08 00:24Z): no samples, so 0 refused, over
   **0** syscall outcomes. Nothing ran in it, so it says nothing either way. The recreate opened **window 16**.
2. **Built** image `0a9d7d99712c`. Before the recreate, the image itself was checked: runtime 2.31.4,
   `apps/_shared/egress.py` present, the RippleTrace legacy router absent, the trace-owner check present,
   4 `.nd` files packaged.
3. **Recreated at 00:29:36Z** with both compose files and both profiles. Healthy in about 60 s, 0 restarts,
   port still `127.0.0.1:8000`.
4. **The handoff's check:** `2.31.4 ['/usr/local/lib/python3.11/site-packages/AINDY']`. `/api/version`:
   `default-apps`, 16 plugins. `/health` 200. Schema heads unchanged: runtime `0020`, app `fl1metrics0001`.
   0 `ERROR` or traceback lines at boot. 0 `executing` agent runs after the restart (no `AgentContinuation`
   line, with nothing in flight to resume).
5. **The app's fixes, live** (designated test account, read-only requests):
   - the retired legacy routes answer 404 even with the shared key;
   - an event naming another user's drop point answers 404;
   - the installed egress guard refuses `postgres` and `mailpit`;
   - `GET /network_bridge/authors` with the shared key lists 0 authors, none of them a sign-in row.

The two `APP_DEPENDS_ON ordering gap` warnings at boot (analytics and masterplan before identity) date from
the repo extraction and are already recorded in `RUNTIME_2_19_0_UPGRADE.md`; not new.

**Still owed:**

- **After a day of normal traffic, from about 2026-11-09 00:30Z:** `aindy_payload_identity_mismatch_total` by
  `syscall`, and the 2.31.3 record's §7 log lines. That read carries over from 2.31.3, whose own windows
  13 to 15 were all too short or too quiet to count.
- **#535:** a release gate opened before midnight local time. It needs a new approve token.
