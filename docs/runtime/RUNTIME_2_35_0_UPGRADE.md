---
title: "Runtime 2.35.0 adoption"
last_verified: "2026-11-11"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.35.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.35.0.md` (tag `v2.35.0`, #954). We come from 2.34.0, live since
2026-11-09 03:46:30Z (`RUNTIME_2_34_0_UPGRADE.md`, whose §7 read 0 identity mismatches and 0 `tenant_mismatch` over
that window). **It answers FR-66 up to its evidence step (D7, ours) and the runtime's part of FR-65.**
**Schema step: Alembic `0022`** (two new tables, `mcp_oauth_clients` and `mcp_oauth_grants`). No ui-kit release (2.1.1 stays).

Pin: `constraints.txt` `aindy-runtime==2.35.0`, floor `>=2.35.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`). `aindy-sdk` floor `>=1.2.1` (§5).

## 1. DEC-128: our MCP reads declare that they read

An MCP server now refuses to start when it would expose a syscall not registered with `read_only=True`, unless
`AINDY_MCP_SERVER_ALLOW_WRITES` is set. Our launcher (`scripts/mcp_server.py`) exposes the runtime's five memory reads,
which the runtime declares, and two of ours, which did not.

**Done, in the same change as the pin** (the keyword is a `TypeError` on 2.34.0): `read_only=True` on
`sys.v1.work.context` and `sys.v1.work.facts`, and on `sys.v1.work.get_claim_truth`, which is also a read though the
launcher does not expose it. `test_mcp_read_access.py` now asserts the flag on every app syscall the launcher lists.

## 2. FastAPI 0.141 → 0.162

- **A literal `null` JSON body** for a non-nullable `Body(...)` is now 422. Our only `Body(...)` parameter is
  `agent_router.py`'s `payload: dict | None = Body(default=None)`, which is nullable; approve/reject take
  `DecisionBody | None = None`, also nullable; the release hand-off's body is required with no default, so `null`
  was already a 422 there. Nothing of ours changes.
- **Unknown keyword arguments** to `Query`/`Body`/… raise at import. The app imports and boots on 0.162 (§6), so there
  are none.

## 3. DEC-126: platform keys over MCP are held to their scopes

Only a multi-tenant MCP server whose callers send `X-Platform-Key`. Our stdio launcher runs as one configured identity:
unaffected.

## 4. FR-66: streamable HTTP and OAuth, off by default

`mcp-server --transport http` and `AINDY_MCP_OAUTH=on` are new and off. **FR-66 closes on D7, which is ours:** a real
claude.ai connector and a real ChatGPT connector each read a memory node, reporting what each registered, whether
discovery from the first `401` worked, what the consent page showed, the tool result and any failure.

**Run 2026-11-11 (owner's go-ahead):** a temporary `--transport http` server with OAuth behind an ngrok tunnel, 02:41Z
→ 03:15Z, then taken down. Both connectors registered, consented, and read a memory node. The report is under FR-66 in
`RUNTIME_FEATURE_REQUESTS.md`; it also found FR-67. The stack is loopback-only again; nothing in compose changed.

When a connected-apps page is built for ordinary users, it calls `GET` / `DELETE /auth/mcp-grants` (session only; the
runtime's console panel admits only admins).

## 5. FR-65: the watcher is `aindy-sdk` 1.2.1

The SDK now ends a session after `AINDY_WATCHER_IDLE_TIMEOUT` seconds without input (default 300), sends
`session_ended` on stop, and installs `aindy-watcher`. **`focused_seconds` and `focus_score` were inflated through
1.1.0** (ten minutes of work read as about 605), so **`focus_quality` before and after the switch is not comparable**:
mark the date when the laptop's watcher moves to 1.2.1.

Our floor is now `>=1.2.1` (1.2.0 calls `classify(window, rules)`, which breaks our launcher's one-argument
`classify`). **Retired 2026-11-11 (owner):** `scripts/watcher.py` and its test are deleted, and the laptop runs
`aindy-watcher` 1.2.1 since **03:20:19Z**; its first `session_started` arrived at 03:20:49Z, attributed to the owner.
**`focus_quality` before and after that time is not comparable.**

## 6. Live

From #596's merge (`dc30980`), image `638ab79a20f4` (built in about 3 minutes: the deps layer moved, the base did not),
up healthy at **2026-11-11 02:36:24Z**, no restarts.

1. **Counters before the recreate** (02:35:46Z, closing the window opened 11-09 03:46:30Z): 0 identity mismatches, 0
   `tenant_mismatch`; 240 model calls, all `key_source="server"`.
2. **The schema step, out-of-band with the api stopped:**
   - `bootstrap-schema` on the new image: `state=upgrade_required operator_action=startup_reconcile exit_code=3`, as
     the handoff said;
   - `docker compose run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile`:
     `stamped alembic_version_runtime from revision 0021 to 0022`;
   - `alembic_version_runtime` reads **`0022`**; `mcp_oauth_clients` and `mcp_oauth_grants` exist. App head
     `gl1layer0001`, unchanged.
3. **The handoff's check:** `2.35.0 ['/usr/local/lib/python3.11/site-packages/AINDY']`, FastAPI `0.162.0`.
   `/health` 200; `default-apps`, `app_plugins_loaded=True`, 16 plugins. No errors in the boot log.
4. **The MCP launcher starts** (`claude mcp get aindy`: connected) with `work.context` and `work.facts` declared
   `read_only`, so DEC-128's startup refusal does not fire.
5. A new identity-counter window opens at 02:36:24Z.
6. **That window was lost** to an overnight reboot of the laptop (2026-11-11, before it was read; signals stop at
   07:35Z). Every container restarted at 17:17Z with the same image, so the next window opened at **17:17:28Z** and
   read 0 identity mismatches and 0 `tenant_mismatch` at 18:01Z. The day-of-traffic read is owed about 11-12 17:20Z.

## 7. Day-of-traffic read, 2026-11-13

The 02:36:24Z window was lost to the reboot (§6, item 6) and never read. The window read here opened at the reboot's
restart of **2026-11-11 17:17:28Z** (image `638ab79a20f4`, no restarts since) and was read at **2026-11-13 05:35Z**,
about 36 hours later.

| Counter | Reading |
|---|---|
| `aindy_payload_identity_mismatch_total` | **0** (declared, never incremented) |
| `aindy_effect_gate_outcomes_total{outcome="tenant_mismatch"}` | **0** (absent; the only outcome is `reserved`, 321) |
| `tenant_mismatch` in the api log since the restart | 0 lines |
| `aindy_llm_key_source_total` | 145, all `key_source="server"`: openai 145 |

The window carried real traffic: 321 gated effects and 145 model calls. Every model call went on the server's key, which
is right under `per_user`, since the owner is the only account that made calls.
