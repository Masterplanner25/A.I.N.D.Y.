"""Masterplan agent tool implementations."""

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
        "genesis.message",
        risk="high",
        description=(
            "Send a message to the Genesis strategic planning session (modifies MasterPlan "
            "state). The session_id must come from the objective or a prior step — the tool "
            "cannot look it up. Do not plan this step without a session_id in hand. Its "
            "result is the session's reply: do not reference its fields from a later step."
        ),
        # FR-33 (runtime 2.20.0): the argument contract — see apps/arm/agents/tools.py.
        args_schema={
            "required": ["message", "session_id"],
            "properties": {
                "message": {"type": "string"},
                "session_id": {
                    "type": "string",
                    "description": "the Genesis session id, from the objective or a prior step",
                },
            },
        },
        capability="tool:genesis.message",
        required_capability="strategic_planning",
        category="planning",
        egress_scope="external_llm",
    )(genesis_message)
    register_tool(
        "market.propose",
        risk="low",
        description=(
            "Record a finding about the user's MARKET for them to confirm: a segment (a kind of "
            "buyer), or an alternative (competitor), channel (where buyers gather), intermediary "
            "(reseller, integrator), voice (analyst, publication) or exemplar (an organisation that "
            "fits a segment). Use it for market research findings instead of leadgen.search or "
            "memory.write. To attach research as evidence, pass a research.query step's result as "
            "`sources` ({\"$from_step\": N, \"path\": \"raw_result\"}): each linked result becomes "
            "its own evidence. Proposes only; the user confirms. Returns {proposed, key, reason}."
        ),
        args_schema={
            "required": ["kind", "name"],
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "segment | alternative | channel | intermediary | voice | exemplar",
                },
                "name": {"type": "string"},
                "note": {"type": "string", "description": "why it matters, one or two sentences"},
                "url": {"type": "string"},
                "segment": {"type": "string", "description": "for an entry: the segment's name, if known"},
                "buyer": {"type": "string", "description": "for a segment: who decides, in what organisation"},
                "problem": {"type": "string", "description": "for a segment: the problem in the buyer's words"},
                "category_terms": {"type": "array", "description": "for a segment: what buyers call it"},
                "works": {"type": "array", "description": "for a segment: names of the user's works serving it"},
                "evidence": {"type": "array", "description": "[{claim, source_url}]; source_url is ONE link"},
                "sources": {
                    "type": "string",
                    "description": "a research.query raw_result; each linked result becomes evidence",
                },
            },
        },
        capability="tool:market.propose",
        required_capability="write_memory",
        category="planning",
        egress_scope="internal",
    )(market_propose)
    register_tool(
        "content.draft",
        risk="low",
        description=(
            "WRITE a document for the user: a plan, outline, article or post draft. Use this for any "
            "prose (arm.generate is for code). Pass what to write from as `sources` by step reference: "
            "memory.recall's result ({\"$from_step\": N, \"path\": \"nodes\"}) for the user's own "
            "published writing, and/or research.query's ({\"$from_step\": N, \"path\": \"raw_result\"}). "
            "It builds on the user's own work first and cites each source. The draft is saved for the "
            "user to read in Collaborator; do not also memory.write it. Returns {draft_id, title, body, "
            "sources_used[]}."
        ),
        args_schema={
            "required": ["brief"],
            "properties": {
                "brief": {"type": "string", "description": "what to write, for whom, and why"},
                "sources": {"description": "step reference(s) to recalled nodes or research text"},
                "title": {"type": "string"},
                "work": {"type": "string", "description": "the name of the user's Work it is for, if one"},
            },
        },
        capability="tool:content.draft",
        required_capability="external_api_call",
        category="writing",
        egress_scope="external_llm",
    )(content_draft)


def genesis_message(args: dict, user_id: str, db) -> dict:
    return _dispatch_tool_syscall("sys.v1.genesis.message", args, user_id, capability="genesis.message")


def content_draft(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.content.draft", args, user_id, capability="content.draft")
    return {"draft_id": data.get("draft_id"), "title": data.get("title"), "body": data.get("body"),
            "sources_used": data.get("sources_used", [])}


def market_propose(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.market.propose", args, user_id, capability="market.propose")
    return {"proposed": data.get("proposed", False), "key": data.get("key"), "reason": data.get("reason")}
