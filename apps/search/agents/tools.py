"""Search and research agent tool implementations."""

from __future__ import annotations

from AINDY.agents.tool_registry import register_tool
from AINDY.agents.tool_syscalls import invoke_tool_syscall


def _dispatch_tool_syscall(syscall_name: str, args: dict, user_id: str, *, capability: str) -> dict:
    return invoke_tool_syscall(
        syscall_name,
        args,
        user_id=user_id,
        capability=capability,
    )


def register() -> None:
    register_tool(
        "search.query",
        risk="medium",
        description=(
            "Unified search over leadgen, research, SEO, and memory surfaces. "
            "Returns a ranked SearchResponse (query, search_type, results[], search_score, memory)."
        ),
        # FR-33 (runtime 2.20.0): the argument contract — see apps/arm/agents/tools.py.
        args_schema={
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "search_type": {
                    "type": "string",
                    "description": "research | leadgen | seo_analysis | memory (default research)",
                },
                "limit": {"type": "integer"},
            },
        },
        capability="tool:search.query",
        required_capability="external_api_call",
        category="search",
        egress_scope="external_web",
    )(search_query)
    register_tool(
        "leadgen.search",
        risk="medium",
        description="Search for B2B leads matching a query. Returns scored leads; does not contact anyone.",
        args_schema={"required": ["query"], "properties": {"query": {"type": "string"}}},
        capability="tool:leadgen.search",
        required_capability="external_api_call",
        category="leadgen",
        egress_scope="external_web",
    )(leadgen_search)
    register_tool(
        "research.query",
        risk="low",
        description="Query external sources for research on a topic.",
        args_schema={"required": ["query"], "properties": {"query": {"type": "string"}}},
        capability="tool:research.query",
        required_capability="external_api_call",
        category="research",
        egress_scope="external_web",
    )(research_query)
    register_tool(
        "leadgen.act",
        risk="medium",
        description=(
            "Act on scored leads — draft outreach for qualified leads, behind a safety gate. "
            "Dry run unless apply=true; with channel='email' and AINDY_SEARCH_OUTREACH_SEND on it "
            "REALLY sends to a hand-entered contact. Every action is tracked and revertible. If "
            "this step is refused for lack of authority the run parks for an operator decision "
            "(skip/abort) rather than failing."
        ),
        args_schema={
            "required": [],
            "properties": {
                "apply": {"type": "boolean", "description": "default false (dry run)"},
                "channel": {"type": "string", "description": "draft | email | handoff (default draft)"},
            },
        },
        capability="tool:leadgen.act",
        required_capability="external_api_call",
        category="leadgen",
        egress_scope="external_llm",
        # AUTHORITY-NEGOTIATION-1 phase 3 evidence (runtime 2.17.0 handoff §3.3, taken
        # 2026-09-16): the one tool of ours whose denial we would rather have PARKED than
        # failed. It is the tool that can email a real person (#369) — and a denial here
        # most plausibly means the run's token expired (24 h TTL) while it sat parked on an
        # approval, or a delegated run's ceiling excludes egress. Failing it would discard
        # the `leadgen.search` work the run already did; parking keeps that work and hands a
        # human the call (`skip` records the step skipped and continues, `abort` fails the
        # run with the reason; there is no `grant` — the gate cannot widen authority).
        # Inert until AINDY_AUTHORITY_NEGOTIATION is on (default off; on in the local
        # profile only, via docker-compose.prod.yml + .env). Resume with
        #   POST /platform/flows/runs/{wait_state.flow_run_id}/resume
        #   {"event_type": "agent.authority.decision", "payload": {"decision": "skip"|"abort"}}
        on_denial="wait",
    )(leadgen_act)


def search_query(args: dict, user_id: str, db) -> dict:
    return _dispatch_tool_syscall(
        "sys.v1.search.query", args, user_id, capability="search.query"
    )


def leadgen_search(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.leadgen.search_ai", args, user_id, capability="leadgen.search_ai")
    return {"leads": data.get("leads", []), "count": data.get("count", 0)}


def research_query(args: dict, user_id: str, db) -> dict:
    return _dispatch_tool_syscall("sys.v1.research.query", args, user_id, capability="research.query")


def leadgen_act(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.leadgen.act", args, user_id, capability="leadgen.act")
    return {
        "status": data.get("status"),
        "actions": data.get("actions", []),
        "skipped": data.get("skipped", []),
        "count": data.get("count", 0),
        "dry_run": data.get("dry_run", False),
        "would_act": data.get("would_act"),
    }
