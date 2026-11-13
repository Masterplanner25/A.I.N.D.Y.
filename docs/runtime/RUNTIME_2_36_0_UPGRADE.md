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

**Done 2026-11-13** (after the recreate, §4):
- dry run: `0 node(s) would get a stored path; 81 path(s) would be rewritten …; left alone: 1904 with no owner`;
- `--yes` at 06:06:55Z: `rewrote 81 path(s) to end with their node's id; left alone: 1904 with no owner`;
- re-run: `ok: … every stored path ends with its node's id (left alone: 1904 with no owner.)`;
- in postgres: 1,892 nodes carry a path, 0 do not end with their id.

**N = 81**, exactly the FR's count: nothing written between 11-08 and the upgrade drifted. **Not-addresses count: none
reported** (the line never appeared). The only skip is **1,904 nodes with no owner**, a different category the handoff
did not mention; reported here, not asked about. **FR-67 closed.**

## 2. FR-68: the consent page behind the tunnel (DEC-132, #958)

No runtime setting: uvicorn's own `FORWARDED_ALLOW_IPS`. Our `mcp` service runs `scripts/mcp_server.py`, whose
`--transport http` ends in the runtime's `serve_http` → plain `uvicorn.run`, so it reads the variable the same way.

**Done:** `docker-compose.prod.yml`, service `mcp`: `FORWARDED_ALLOW_IPS: "${FORWARDED_ALLOW_IPS:-172.19.0.0/16}"`,
the compose network's subnet (`docker network inspect aindy-apps-monolith_default`), not the tunnel container's
address, which changes on recreate. Never `*`.

**Checked 2026-11-13:** one unauthenticated `GET $AINDY_MCP_PUBLIC_URL/mcp` through the tunnel answered 401, and
`mcp`'s access log recorded the caller's own public (IPv6) address, not the tunnel container's `172.19.0.x`. The
consent page's limit now keys per caller. **FR-68 closed.**

## 3. nodus-lang 5.16.0 (#959)

Error columns in a Nodus script's errors move to what is called; lines are unchanged. Nothing of ours parses columns.
`StagedFlipWarning` reaches only a script that calls `resume_workflow` itself; none of our `.nd` files do, and none use
`checkpoint`.

## 4. Live

From #609's merge (`0eff38c`), image `4dfd26687fd9` (built in 2 min 26 s; `api` and `mcp` were stopped for the build,
host RAM 1.0 GB free). Also takes #604–#606 live.

1. **Counters before the recreate** (05:53:08Z, closing the 2.35.0 window opened 11-11 17:17:28Z): 0 identity
   mismatches, 0 `tenant_mismatch`; 328 gated effects, 146 model calls, all `key_source="server"`.
2. `api` and `mcp` recreated at **05:55:58Z**, `api` healthy at 05:56:34Z. Postgres: 0 reinitialisations.
3. **The handoff's check:** `2.36.0 5.16.0 ['/usr/local/lib/python3.11/site-packages/AINDY']`. `/health` 200;
   `default-apps`, `app_plugins_loaded=True`, 16 plugins. No errors in the boot log.
4. Schema heads unchanged: runtime `0022`, app `gl1layer0001`.
5. Durable continuation: no `AgentContinuation` lines, 0 agent runs left `executing`.
6. A new identity-counter window opens at **05:55:58Z**.
