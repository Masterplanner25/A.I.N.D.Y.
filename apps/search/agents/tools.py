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
            "Args: {query, search_type?: 'research'|'leadgen'|'seo_analysis'|'memory', limit?}. "
            "Returns a ranked SearchResponse (query, search_type, results[], search_score, memory)."
        ),
        capability="tool:search.query",
        required_capability="external_api_call",
        category="search",
        egress_scope="external_web",
    )(search_query)
    register_tool(
        "leadgen.search",
        risk="medium",
        description=(
            "Search for B2B leads matching a query. Args: {query: str (required)}. "
            "Returns scored leads; does not contact anyone."
        ),
        capability="tool:leadgen.search",
        required_capability="external_api_call",
        category="leadgen",
        egress_scope="external_web",
    )(leadgen_search)
    register_tool(
        "research.query",
        risk="low",
        description=(
            "Query external sources for research on a topic. Args: {query: str (required)}."
        ),
        capability="tool:research.query",
        required_capability="external_api_call",
        category="research",
        egress_scope="external_web",
    )(research_query)
    register_tool(
        "leadgen.act",
        risk="medium",
        description=(
            "Act on scored leads — draft (never send) outreach for qualified leads, "
            "behind a safety gate. Args: {apply?: bool, channel?: 'draft'|'email'|'handoff'}. "
            "Dry run unless apply=true; every action is tracked and revertible."
        ),
        capability="tool:leadgen.act",
        required_capability="external_api_call",
        category="leadgen",
        egress_scope="external_llm",
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
