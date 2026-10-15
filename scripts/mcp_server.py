"""Serve A.I.N.D.Y. to an outside AI (Claude Code, Claude Desktop, ChatGPT…) over MCP, read-only.

Owner, 2026-10-14: the Infinity Algorithm is the product, and other AIs are access to its state.
This is that access, for one person on one machine: stdio, acting as AINDY_MCP_SERVER_USER_ID.

Why a script and not `aindy-runtime mcp-server`: the runtime's command never loads the app's
plugins, so none of our syscalls exist in its process and an allowlisted one is skipped as "not
registered" (FR-53). This loads them, then hands over to the runtime's own server.

The allowlist is READ-ONLY and every entry acts as the caller's identity. Several of our older
syscalls take `user_id` from the PAYLOAD and the dispatcher never checks it against the caller
(FR-53), so over MCP they would read whoever's id the outside AI sends. They are not exposed.

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

    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # anything printed while the app loads must not corrupt the MCP channel
    try:
        from AINDY.platform_layer.registry import load_plugins

        load_plugins()
    finally:
        sys.stdout = real_stdout

    from AINDY.platform_layer import mcp_server

    mcp_server.serve_stdio()


if __name__ == "__main__":
    main()
