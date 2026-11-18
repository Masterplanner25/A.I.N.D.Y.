---
title: "Runtime 2.37.0 adoption"
last_verified: "2026-11-18"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.37.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.37.0.md` (tag `v2.37.0`, #979). We come from 2.36.1, live since
2026-11-18 03:40:58Z. **It answers FR-70.** **No schema step:** Alembic stays `0022`, schema contract `2026-11-09`. No
dependency pin moved; no ui-kit or aindy-sdk release. Nothing changes for a route that does not use the new dependency.

Pin: `constraints.txt` `aindy-runtime==2.37.0`, floor `>=2.37.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`).

## 1. FR-70: `get_activity_caller` (DEC-133, #978)

The runtime took our option 1, a public auth dependency; option 2 (an app-registrable exclusive scope) was declined
until a second app needs a key separate from the watcher key.

**Our change, in this PR:** `_directing_caller` in `apps/automation/routes/directing_router.py` depends on
`get_activity_caller` instead of `get_current_user`. Nothing else in the route changes: the principal has the same
shape, and `current_user["sub"]` is still the user id.

| Credential on `POST /apps/directing/events` | Before | Now |
|---|---|---|
| A signed-in session | admitted | admitted |
| The watcher key (`watcher.signals` only) | 401/403 | **admitted** |
| A platform key with `watcher.signals` or `platform.admin` | admitted | admitted |
| Any other platform key | admitted | **403** |
| The shared `X-API-Key` alone | admitted as no user | **401** |

The narrowing costs nothing: nothing posts to the route yet (phase B is the first client, `directing_events` is
empty). `test_the_route_admits_the_watcher_key_through_get_activity_caller` pins the dependency and that no
`enforce_api_key_scope` (which would refuse the watcher key again) sits beside it.

**FR-70 closes** on phase B: the hook's first 2xx with a watcher-only key, and a 403 from the same key on another app
route (the control the runtime asked for). Phase B is unblocked.

## 2. Live

Merged as #622. Built 2026-11-18 (image `44bf0e2c0dac`, api and `mcp` stopped first for memory) and brought up with all
three profiles at **05:34:09Z**; api healthy at 05:34:39Z.

```
$ docker exec <api> python -c "...get_activity_caller..."
2.37.0 get_activity_caller ['/usr/local/lib/python3.11/site-packages/AINDY']
```

`mcp` reports 2.37.0 too. Runtime schema head `0022`, `/health` 200, the public `/mcp` 401 without a token, no postgres
reinitialisation.

**The key, probed live at 05:35Z with the test account** (a fresh key from `POST /watcher/keys`, scopes
`['watcher.signals']` only):

| Request | Answer |
|---|---|
| `POST /apps/directing/events` with the watcher key | **200**, `accepted: 1` |
| `GET /apps/goals` with the same key (the control) | **403** |
| `POST /apps/directing/events` with no credential | 401 |
| the same post after `DELETE /watcher/keys/{id}` (204) | 401 |

The probe row was deleted; `directing_events` is empty. Both halves the runtime asked for hold. **FR-70 stays open
only for its stated proof**: phase B's hook posting with the owner's own watcher key.

**Counters:** the window opened 2026-11-18 03:40:58Z (2.36.1) was read just before the stop, at 05:30:44Z: **0**
identity mismatches and **0** `tenant_mismatch` (neither series present), 22 gated effects (`reserved`). A new window
opened at 05:34:09Z.
