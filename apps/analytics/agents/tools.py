"""Reasoning agent tool (ARM/Reasoning Phase 3 follow-up).

Exposes the autonomous-reasoning service to agents as the read-only
`reasoning.evaluate` tool, so an agent can ask "what should I do next?" mid-run.
Registered via the runtime's `register_tool` surface — no runtime edits. The
capability wiring lives in `capabilities.py` so plans using this tool resolve a
capability token and auto-approve at low risk.
"""

from __future__ import annotations

from AINDY.agents.tool_registry import register_tool


def reasoning_evaluate(args: dict, user_id: str, db) -> dict:
    """Return the current autonomous-reasoning recommendation for the user.

    Read-only, internal. Output: ``{available, decision_type, reason,
    next_action_type, next_action_title, suggested_goal, execution_intent}``.
    """
    from apps.analytics.services.reasoning import recommend_next_action

    recommendation = recommend_next_action(user_id, db)
    if not recommendation:
        return {"available": False, "reason": "no_score_snapshot"}
    return {"available": True, **recommendation}


def register() -> None:
    register_tool(
        "reasoning.evaluate",
        risk="low",
        description=(
            "Evaluate the user's current state and return the autonomous-reasoning "
            "recommendation: decision_type, reason, next action, and execution intent. "
            "Read-only. Use to decide what to do next. Takes no arguments."
        ),
        # FR-33 (runtime 2.20.0): the argument contract — see apps/arm/agents/tools.py.
        args_schema={"required": [], "properties": {}},
        capability="tool:reasoning.evaluate",
        required_capability="read_reasoning",
        category="analysis",
        egress_scope="internal",
    )(reasoning_evaluate)
