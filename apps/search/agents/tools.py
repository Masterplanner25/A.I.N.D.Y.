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
            "Returns {query, search_type, results[], search_score, memory}, a ranked SearchResponse; "
            "each result has title, snippet and url."
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
        description=(
            "Find BUYERS inside one of the user's confirmed market segments (name it in `segment`; "
            "the segments are in your context). It searches where that buyer shows up (job boards "
            "hiring for the problem by default; where='channels' for the segment's confirmed "
            "channels), judges each result, saves the buyers as leads leadgen.act can draft "
            "outreach for, and proposes the rest (competitors, analysts) as market entries. "
            "Without a segment it is a plain web search that saves nothing. Market questions "
            "(who the buyer is, competitors) belong to research.query + market.propose. Does not "
            "contact anyone. Returns {leads[], count, saved, segment, proposed[]}."
        ),
        args_schema={
            "required": [],
            "properties": {
                "segment": {"type": "string", "description": "a confirmed segment's name"},
                "where": {"type": "string", "description": "hiring (default) | channels | web"},
                "query": {"type": "string", "description": "only without a segment: a plain web search"},
            },
        },
        capability="tool:leadgen.search",
        required_capability="external_api_call",
        category="leadgen",
        egress_scope="external_web",
    )(leadgen_search)
    register_tool(
        "research.query",
        risk="low",
        description=(
            "Query external sources for research on a topic. Returns {raw_result}: the "
            "research as one text string (reference it with path \"raw_result\")."
        ),
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
            "(skip/abort) rather than failing. Returns {status, actions[], skipped[], count, "
            "dry_run, would_act}."
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
    # Inside a segment (MARKET_MODEL_SPEC §5): judged, and only buyers saved. Outside one, a plain
    # web search that saves nothing (§9 decision 4). History: until 2026-09-28 this was the raw
    # search, unscored and unsaved (run 8cdb97ef); then the scored search, which saved a
    # competitor's listicle, an analyst's article and a trade story as leads (run 8b75d75d),
    # because it searched the open web for a topic.
    segment = str(args.get("segment") or "").strip()
    if segment:
        data = _dispatch_tool_syscall(
            "sys.v1.leadgen.search_segment", {"segment": segment, "where": args.get("where") or "hiring"},
            user_id, capability="leadgen.search",
        )
        return {"leads": data.get("leads", []), "count": data.get("count", 0), "saved": True,
                "segment": data.get("segment"), "proposed": data.get("proposed", [])}
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("leadgen.search needs a segment (or, for a plain web search, a query)")
    data = _dispatch_tool_syscall("sys.v1.leadgen.search_ai", {"query": query}, user_id, capability="leadgen.search_ai")
    leads = data.get("leads", [])
    return {"leads": leads, "count": len(leads), "saved": False, "segment": None, "proposed": []}


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
