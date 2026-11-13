---
title: "Runtime 2.36.0 adoption"
last_verified: "2026-11-13"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.36.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.36.0.md` (tag `v2.36.0`, #960). We come from 2.35.0, live since
2026-11-11 17:17:28Z (the post-reboot restart; `RUNTIME_2_35_0_UPGRADE.md` §7 read 0 identity mismatches and 0
`tenant_mismatch` over that window). **It answers FR-67 and FR-68.**
**No schema step:** Alembic stays `0022`, schema contract `2026-11-09`. No ui-kit or aindy-sdk release.
nodus-lang moves 5.15.1 → 5.16.0 through the runtime's pin (we do not pin it).

Pin: `constraints.txt` `aindy-runtime==2.36.0`, floor `>=2.36.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`).

## 1. FR-67: a memory node's path ends with its own id (DEC-131, #957)

`MemoryNodeDAO.save` now takes the row's id from the path's last segment, so new writes cannot drift.
`memory.write` now refuses a `path` that names its leaf (`failure_class: invalid`).

**Our callers, checked:** the three `sys.v1.memory.write` sites (`apps/agent/agents/tools.py` `memory_write`,
`apps/agent/agents/runtime_extensions.py` run findings, `apps/automation/services/release_handoff_service.py` the
release outcome note) pass `content`, `tags`, `node_type` and `source`, never `path`. Each keeps the node's **id**
(`handoff.memory_node_id`, the tool's `{node_id}`), which the backfill never changes. Nothing of ours stores a path, so
the old addresses stopping is invisible to us.

**Owed after the rebuild:** `aindy-runtime memory backfill-paths`, dry run then `--yes`; report N (the runtime expects
≥ 81) and the not-addresses count. That closes FR-67.

## 2. FR-68: the consent page behind the tunnel (DEC-132, #958)

No runtime setting: uvicorn's own `FORWARDED_ALLOW_IPS`. Our `mcp` service runs `scripts/mcp_server.py`, whose
`--transport http` ends in the runtime's `serve_http` → plain `uvicorn.run`, so it reads the variable the same way.

**Done:** `docker-compose.prod.yml`, service `mcp`: `FORWARDED_ALLOW_IPS: "${FORWARDED_ALLOW_IPS:-172.19.0.0/16}"`,
the compose network's subnet (`docker network inspect aindy-apps-monolith_default`), not the tunnel container's
address, which changes on recreate. Never `*`.

**Owed after the recreate:** the access log's client address for a public request is the caller's, not the tunnel's
(`172.19.0.x`). That closes FR-68.

## 3. nodus-lang 5.16.0 (#959)

Error columns in a Nodus script's errors move to what is called; lines are unchanged. Nothing of ours parses columns.
`StagedFlipWarning` reaches only a script that calls `resume_workflow` itself; none of our `.nd` files do, and none use
`checkpoint`.

## 4. Live

Owed: one rebuild of the api image (also takes #604–#606 live), recreate `api` and `mcp`, then the handoff's check:

```bash
docker exec <api-container> python -c "import AINDY, AINDY._version as v, importlib.metadata as m; print(v.__version__, m.version('nodus-lang'), list(AINDY.__path__))"
# expect: 2.36.0 5.16.0 ['/usr/local/lib/python3.11/site-packages/AINDY']
```

A new identity-counter window opens at the recreate.
