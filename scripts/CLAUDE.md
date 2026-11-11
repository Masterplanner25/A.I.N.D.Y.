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
- **Every tool the launcher lists must be registered `read_only=True`** (2.35.0, DEC-128), or the server
  refuses to start, naming it. `test_mcp_read_access.py` asserts it.

## claude.ai and ChatGPT: the public `/mcp` (owner, 2026-11-11)

FR-66's D7 proved it on 2026-11-11 (report in the FR register); the owner then asked for it for real.

- **What runs:** compose profile `public-mcp`. Service `mcp` is this launcher with `--transport http` (same image
  and environment as the api, port 8080 on loopback, its own small DB pool); service `mcp-tunnel` is an ngrok agent
  forwarding `$AINDY_MCP_PUBLIC_URL` to `mcp:8080`, and nothing else. **The api is never behind the tunnel**: through
  it, `/health`, `/auth/login` and `/docs` are 404. Both need `AINDY_MCP_PUBLIC_URL` and `NGROK_AUTHTOKEN` in `.env`.
- **The launcher refuses `--transport http` without `AINDY_MCP_OAUTH=on`.** Without OAuth the runtime answers every
  HTTP caller as one configured user. With it, `/mcp` takes only its own 1-hour tokens, each held to the scopes the
  user approved on the consent page (sign-in with an existing account; registration stays closed).
- **Anything added to `READ_ONLY_TOOLS` is public** to whoever holds a grant. Same rule as before, higher stakes.
- **Connect:** claude.ai "Add custom connector" with **Sign in now** and **Register automatically (DCR)** (not CIMD,
  which we don't serve); ChatGPT developer-mode connector with OAuth. The free ngrok domain shows a browser warning
  once before the consent page: **Visit Site**.
- **See and end connections:** `GET` / `DELETE /auth/mcp-grants` from a signed-in session (each writes
  `mcp_grant.created` / `.revoked`, source `mcp.oauth`), which **Settings → Connected apps** calls
  (`ConnectedAppsCard.jsx`, 2026-11-11). The runtime has no command to delete an OAuth client: a client with no live
  grant can be deleted from `mcp_oauth_clients` (its grants cascade; the audit events stay), as two were on 11-11.
- **The consent page's rate limit (10 attempts a minute) is global here**, because every request arrives from the
  tunnel's address (FR-68 asks the runtime to trust a named proxy's `X-Forwarded-For`).
- **Take it down:** `docker compose ... --profile public-mcp stop mcp-tunnel mcp`. 
- **The owner's own Nodus MCP server** (`127.0.0.1:8765`, its own sign-in task) is separate from this one. **Its public
  tunnel `nodusmcpserver.ngrok.io` stays off** (owner, 2026-11-11): that server has no auth and exposes `nodus_exec`.
  It comes back only once it has sign-in, the way this `/mcp` does.
- **Next:** the release handoff (`docs/specs/RELEASE_HANDOFF_SPEC.md`). Its MCP handoff tool is the
  first write tool here, and it only *records* a handoff: the api's watcher does the work, so no wait is
  ever registered outside the api (FR-44).

## The watcher feeds `focus_quality` (audit D1, owner 2026-11-08)

`focus_quality` is 15% of the score and read 50 in every row until a watcher reported. The runtime ships the watcher:
`/watcher` routes with per-user keys (DEC-117), and a Windows client in `aindy-sdk`. Until 1.2.1 its signals couldn't
count for anyone (FR-65, shipped).

- **Run the SDK's `aindy-watcher` (aindy-sdk >= 1.2.1), from the venv.** Since 2026-11-11 there is no launcher of ours:
  1.2.1 sends a per-user key as `X-Platform-Key`, ends a session after `AINDY_WATCHER_IDLE_TIMEOUT` seconds without
  input (default 300), and sends `session_ended` on stop (FR-65). The SDK reads the key from the environment only, so
  from PowerShell, at the repo root:
  `$env:AINDY_WATCHER_KEY = (Get-Content ~/.aindy/watcher_key -Raw).Trim(); $env:AINDY_WATCHER_API_URL = 'http://127.0.0.1:8000'; venv/Scripts/aindy-watcher.exe`
  (`--dry-run` first to see what it would send; set the URL, since the SDK defaults to `localhost`).
- **On the owner's laptop it starts at sign-in** (2026-11-11): the scheduled task "A.I.N.D.Y. watcher" runs
  `~/.aindy/start-watcher.ps1` 2 minutes after sign-in, which does the line above unless a watcher is already running
  (log `~/.aindy/watcher.log`). "A.I.N.D.Y. client (Vite)" does the same for `npm run dev` (`~/.aindy/start-vite.ps1`,
  log `~/.aindy/vite.log`). The stack itself comes back with Docker Desktop (start at login on; `restart: unless-stopped`),
  `mcp` and `mcp-tunnel` included. Both scripts live outside the repo.
- **`focus_quality` before 2026-11-11 03:20:19Z is not comparable with after.** SDK 1.1.0 and earlier inflated
  `focused_seconds` and `focus_score` (ten minutes read as about 605) and fired `distraction_detected` too early.
- **The key:** a watcher key from Settings (Watcher key), in `AINDY_WATCHER_KEY` or `~/.aindy/watcher_key`. Never the
  shared `AINDY_API_KEY`, which must not live on a laptop.
- **Only `session_ended` moves the score.** `focus_quality` reads `session_ended`, `distraction_detected` and
  `focus_achieved` over 14 days.
- **The watcher was first used 2026-11-08** (owner). FR-65 is shipped; file a new edge as its own FR.
