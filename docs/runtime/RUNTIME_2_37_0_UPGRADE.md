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

Owed after merge: `build api`, then `up` with all three profiles (`mcp` shares the image), then the handoff's check:

```bash
docker exec <api> python -c "import AINDY, AINDY._version as v; from AINDY.services.auth_service import get_activity_caller; print(v.__version__, get_activity_caller.__name__, list(AINDY.__path__))"
# expect: 2.37.0 get_activity_caller ['/usr/local/lib/python3.11/site-packages/AINDY']
```

The recreate closes the counter window opened 2026-11-18 03:40:58Z and opens a new one.
