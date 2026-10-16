"""Serve A.I.N.D.Y. to an outside AI (Claude Code, Claude Desktop, ChatGPT…) over MCP, read-only.

Owner, 2026-10-14: the Infinity Algorithm is the product, and other AIs are access to its state.
This is that access, for one person on one machine: stdio, acting as AINDY_MCP_SERVER_USER_ID.

Why a script and not `aindy-runtime mcp-server`: since runtime 2.28.0 (FR-53 a) the runtime's server
loads our plugins itself, so this no longer does. What it still adds is the allowlist below, read-only,
and the refusal of `AINDY_MCP_SERVER_ALLOW_WRITES`. Phase 2 of the release handoff adds the first write
tool here, deliberately, one at a time.

Every entry acts as the caller's identity and reads `ctx.user_id`. Since 2.28.0 (FR-53 b) the runtime
also refuses an MCP call whose payload `user_id` names someone else, so exposing a syscall that reads a
payload id is now safe at the transport. We still expose only `ctx.user_id` readers: in-process
dispatch is not yet checked (`PAYLOAD-IDENTITY-DISPATCH-1`), and the rule costs nothing.

Claude Code, from the repo root:

    claude mcp add aindy -- docker exec -i -e AINDY_MCP_SERVER_USER_ID=<your user id> \
        aindy-apps-monolith-api-1 python /app/scripts/mcp_server.py

stdout is the MCP channel: nothing here may print to it, so logging goes to stderr.
"""
from __future__ import annotations

import logging
import os
import sys

#: Exposed by default. All read-only, all scoped to the caller's identity.
READ_ONLY_TOOLS = (
    # The runtime's memory reads (its own default allowlist).
    "sys.v1.memory.read",
    "sys.v1.memory.search",
    "sys.v1.memory.list",
    "sys.v1.memory.tree",
    "sys.v1.memory.trace",
    # Ours: the owner's Works, and everything known about one of them.
    "sys.v1.work.context",
    "sys.v1.work.facts",
)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ.setdefault("AINDY_MCP_SERVER_TOOLS", ",".join(READ_ONLY_TOOLS))
    if os.environ.get("AINDY_MCP_SERVER_ALLOW_WRITES", "").strip().lower() in {"1", "true", "yes"}:
        sys.exit("refusing: this launcher is read-only; AINDY_MCP_SERVER_ALLOW_WRITES must be unset")

    # The runtime loads our plugins with stdout held on stderr at the fd level (2.28.0, FR-53 a). A
    # plugin that fails to load stops the server, as it stops the api; `AINDY_BOOT_PROFILE=platform-only`
    # serves the runtime's tools alone while one is broken (DEC-101).
    from AINDY.platform_layer import mcp_server

    mcp_server.serve_stdio()


if __name__ == "__main__":
    main()
