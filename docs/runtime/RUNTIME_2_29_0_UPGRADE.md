---
title: "Runtime 2.29.0 adoption"
last_verified: "2026-10-30"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.29.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.29.0.md` (tag `v2.29.0`, `d4a3557`, #867). No schema
change (head stays `0020`, contract `2026-09-20`), no ui-kit release (2.1.1 stays).

## 1. The dispatcher refuses a payload `user_id` that is not the caller's (#866, DEC-103)

A non-empty payload `user_id` that differs from `ctx.user_id` now returns `TENANT_VIOLATION`
(`failure_class: permission`), and the handler does not run. Absent, `None`, `""` and the caller's own
id in any UUID spelling pass. The check runs before the quota and the idempotency gate.
`aindy_payload_identity_mismatch_total{syscall}` keeps counting in both modes; **on 2.29.0 a label is
a refused call.**

**We adopt it without `AINDY_PAYLOAD_IDENTITY_DISPATCH=observe`.** The evidence:

- **Windows read:** window 1 read 0 over 1,496 dispatches, window 2 was lost, window 3 read 0 over 793
  and window 4 read 0 over 236 (10-30 → 11-01 06:16Z) (`RUNTIME_2_28_0_UPGRADE.md` §4).
- **Call sites:** all 93 in-process dispatch sites were checked on 2026-10-29. One would be refused:
  `watcher_signals_list_node`, whose payload `user_id` was a *filter*. It is fixed in #506, which also
  closed a cross-tenant read: `sys.v1.watcher.query` returned every user's signals when no `user_id`
  was given.
- **Payload-id fallbacks removed:** #507 (`automation.list_*`) and #508 (loop-adjustment create/update)
  took out the remaining reads where a payload id could stand in for the caller. All three are in
  `main` before this pin, so they ship in the same image.

**Refused on purpose:** a flow whose whole state is its payload (`_syscall_node` in
`tasks_flows.py` and `system_flows.py`), started through `/platform` with another user's id in its
state.

**If a label appears after the rebuild:** it names the refused syscall. Fix the caller (give it a
per-user context, never a payload key) and report the label to the runtime. Use the `observe` flag
only as a short rollout aid while that fix ships, and remove it after.

## 2. setuptools 84.1.0 (#865): only through the `security` extra

GHSA-xmj3-9gf7-h52w and GHSA-grgh-hr87-3jpw are both low-severity and Windows-only, and the runtime
has no exposure to either. The runtime declares `setuptools>=84.1.0` **only under its `security`
extra**. With `aindy-runtime[mcp]` the image keeps the base image's setuptools (79.0.1 in the 2.28.2
container), so the handoff's expected `84.1.0` would not hold. **We now install
`aindy-runtime[mcp,security]`.** No ignores, per the runtime's ask.

## 3. Done here

- **Pin and floor together:** `constraints.txt` `==2.29.0` and `pyproject.toml`
  `aindy-runtime[mcp,security]>=2.29.0,<3.0`, plus the contract test.
- **CLAUDE.md:** the contract block, the Nodus "a workflow acts as one user" note and the MCP
  `ctx.user_id` note now say in-process dispatch refuses.
- **No change:** `python-dotenv` is still `==1.2.3`, so the pytest-env hold stays.

## 4. Rebuild: after the owner's article

Held until share drafts' first real run (an article published 2026-10-30) has finished, so the
recreate does not cut the poll → archive → share chain. Then, in this order:

1. **Window 4:** on the 2.28.2 container, `curl -s localhost:8000/metrics/ | grep
   aindy_payload_identity_mismatch_total`. Expect HELP/TYPE only. Record it in
   `RUNTIME_2_28_0_UPGRADE.md` §4. **Done 2026-11-01 06:16Z: HELP/TYPE only, 0 over 236 dispatches.**
   The drafts for the article (`dp-9331…`, "Prototyping with AI") were made at 06:07Z, so the chain
   was finished before the read.
2. **Rebuild and recreate** (both compose files, both profiles). Check:

   ```bash
   docker exec <api> python -c "import AINDY, AINDY._version as v, setuptools; print(v.__version__, list(AINDY.__path__), setuptools.__version__)"
   # expect: 2.29.0 ['/usr/local/lib/python3.11/site-packages/AINDY'] and setuptools >= 84.1.0
   # (a range: 84.2.1 was the newest on 2026-10-30, so the handoff's exact "84.1.0" will read higher)
   ```

   Then `/health`, the schema head, and the `AgentContinuation` log.
3. **After a day of traffic:** read the counter again. Any label is a refused call: send the runtime
   its `{syscall}`.
