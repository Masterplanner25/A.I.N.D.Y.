"""Serve A.I.N.D.Y. to an outside AI (Claude Code, Claude Desktop, ChatGPT…) over MCP, read-only.

Owner, 2026-10-14: the Infinity Algorithm is the product, and other AIs are access to its state.
This is that access, for one person on one machine: stdio, acting as AINDY_MCP_SERVER_USER_ID.

Why a script and not `aindy-runtime mcp-server`: since runtime 2.28.0 (FR-53 a) the runtime's server
loads our plugins itself, so this no longer does. What it still adds is the allowlist below, read-only,
and the refusal of `AINDY_MCP_SERVER_ALLOW_WRITES`. Phase 2 of the release handoff adds the first write
tool here, deliberately, one at a time.

Every entry acts as the caller's identity and reads `ctx.user_id`. The runtime refuses a payload
`user_id` naming someone else, over MCP since 2.28.0 (FR-53 b) and in-process since 2.29.0 (DEC-103).
We still expose only `ctx.user_id` readers, because the rule costs nothing.

**The allowlist is assigned, never inherited.** Since 2.31.1 (DEC-112) the server grants each tool the
capability its syscall declares, so any syscall named in `AINDY_MCP_SERVER_TOOLS` is really callable:
an inherited value naming `sys.v1.memory.delete` would hard-delete. Add a tool to the list below.

Claude Code, from the repo root:

    claude mcp add aindy -- docker exec -i -e AINDY_MCP_SERVER_USER_ID=<your user id> \
        aindy-apps-monolith-api-1 python /app/scripts/mcp_server.py

claude.ai and ChatGPT (owner, 2026-11-11, after FR-66's D7): the same allowlist over streamable HTTP at `/mcp`,
with the runtime's OAuth (2.35.0, DEC-129/130), as the compose service `mcp` behind the `mcp-tunnel` service:

    python /app/scripts/mcp_server.py --transport http --host 0.0.0.0 --port 8080

Over HTTP the launcher refuses to start unless `AINDY_MCP_OAUTH` is on: without it the runtime would answer every
caller as one configured user, and this server is meant to be public.

Over stdio, stdout is the MCP channel: nothing here may print to it, so logging goes to stderr.
"""
from __future__ import annotations

import argparse
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


def _oauth_on() -> bool:
    return os.environ.get("AINDY_MCP_OAUTH", "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="A.I.N.D.Y. read-only MCP server")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ["AINDY_MCP_SERVER_TOOLS"] = ",".join(READ_ONLY_TOOLS)
    if os.environ.get("AINDY_MCP_SERVER_ALLOW_WRITES", "").strip().lower() in {"1", "true", "yes"}:
        sys.exit("refusing: this launcher is read-only; AINDY_MCP_SERVER_ALLOW_WRITES must be unset")
    if args.transport == "http" and not _oauth_on():
        sys.exit("refusing: --transport http serves the public; set AINDY_MCP_OAUTH=on and AINDY_MCP_PUBLIC_URL")

    # The runtime loads our plugins with stdout held on stderr at the fd level (2.28.0, FR-53 a). A
    # plugin that fails to load stops the server, as it stops the api; `AINDY_BOOT_PROFILE=platform-only`
    # serves the runtime's tools alone while one is broken (DEC-101).
    from AINDY.platform_layer import mcp_server

    if args.transport == "http":
        logging.getLogger().setLevel(logging.INFO)  # not the MCP channel here; the log is the record
        mcp_server.serve_http(host=args.host, port=args.port)
    else:
        mcp_server.serve_stdio()


if __name__ == "__main__":
    main()
