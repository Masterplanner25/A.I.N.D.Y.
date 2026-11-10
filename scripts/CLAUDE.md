# Scripts: the MCP launcher and the watcher

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## Another AI reading A.I.N.D.Y. — MCP (since #468)

Owner, 2026-10-14 (#467): **the Infinity Algorithm is the product, and other AIs, repos and outside
systems are *access* to its state, never a second product.** Judge that work by the same rule:
does it feed the algorithm? Persist outcomes and references, not transcripts.

- **Claude Code is connected** as MCP server `aindy` (`claude mcp add --scope local`, so it lives in
  the user's `~/.claude.json`, not the repo). It reads `work_context`, `work_facts {work}` and the five
  memory reads **as the owner, read-only**, through
  `docker exec -i -e AINDY_MCP_SERVER_USER_ID=<uid> <api> python /app/scripts/mcp_server.py`.
  **Use these for the owner's Work facts instead of asking for a paste.** The api container must be up.
- **Why a launcher and not `aindy-runtime mcp-server`:** since 2.28.0 (FR-53a) the runtime's server
  loads our plugins itself, so the launcher no longer does. It keeps the read-only allowlist and refuses
  `AINDY_MCP_SERVER_ALLOW_WRITES`. A plugin that fails to load now stops the MCP server;
  `AINDY_BOOT_PROFILE=platform-only` serves the runtime's tools alone (DEC-101).
- **Expose only syscalls that read `ctx.user_id`.** Since 2.28.0 (FR-53b) the MCP transport refuses a
  payload `user_id` naming another user, and since 2.29.0 (DEC-103) so does in-process dispatch,
  so a payload can no longer name another user anywhere. Still expose only `ctx.user_id` readers: a
  handler that *falls back* to a payload id (`get_objective_attainment`, `masterplan.get_active`) is
  one refusal away from acting for the wrong user. #506–#508 removed ours from `automation.*` and
  `watcher.query`. Read `aindy_payload_identity_mismatch_total` before each api rebuild. `test_mcp_read_access.py` reads every exposed handler's source.
- **Over MCP a syscall is granted the capability it declares** (2.31.1, DEC-112). Before that it was
  inferred from the name, which is why `sys.v1.work.context` declares `work.context`, and why
  `memory.search`, `.tree` and `.trace` were refused. In-process `sys()` still infers from the name
  (below). **Any syscall named in `AINDY_MCP_SERVER_TOOLS` is really callable**, so the launcher assigns
  that list rather than inheriting it. To expose a tool, add it to `READ_ONLY_TOOLS`.
- **To probe it**, spawn the launcher from an `mcp` SDK client inside the container
  (`stdio_client(StdioServerParameters(command="python", args=["/app/scripts/mcp_server.py"]))`). In
  mcp 2.x the result field is `is_error`, not `isError`. A new MCP server reaches a Claude Code session
  only at session start.
- **Next:** the release handoff (`docs/specs/RELEASE_HANDOFF_SPEC.md`). Its MCP handoff tool is the
  first write tool here, and it only *records* a handoff: the api's watcher does the work, so no wait is
  ever registered outside the api (FR-44).

## The watcher feeds `focus_quality` (audit D1, owner 2026-11-08)

`focus_quality` is 15% of the score and read 50 in every row until a watcher reported. The runtime ships the watcher:
`/watcher` routes with per-user keys (DEC-117), and a Windows client in `aindy-sdk`. As shipped, its signals can't count
for anyone (FR-65).

- **Run it with `scripts/watcher.py`, never the SDK directly.** The launcher sends the key as `X-Platform-Key` and ends
  a session after `AINDY_WATCHER_IDLE_MINUTES` (default 5) of keyboard and mouse idle. The SDK alone ends one only on a
  screen lock.
- **The key:** a watcher key from Settings (Watcher key), in `AINDY_WATCHER_KEY` or `~/.aindy/watcher_key`. Never the
  shared `AINDY_API_KEY`, which must not live on a laptop.
- **Only `session_ended` moves the score.** `focus_quality` reads `session_ended`, `distraction_detected` and
  `focus_achieved` over 14 days.
- **The watcher had never been used before** (owner). Expect to find its edges, and file them on FR-65.
