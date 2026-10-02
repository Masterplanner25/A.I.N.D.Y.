"""What each of our agent tools returns, as `register_tool(..., result_schema=...)` (runtime 2.25.0, FR-48).

The planner's catalog line shows these as `returns={...}`, and with `AINDY_PLAN_STEP_REFERENCES` on
(this stack) every `{"$from_step": N, "path": "…"}` is checked against step N's schema at plan time,
before anything runs. That is the check run `615b67ea` needed: `"path": "results"` on `research.query`
would have been refused with the tool's real shape in the error, instead of failing at step 2 after
the research had been paid for.

The dialect is `args_schema`'s. A node that lists `properties` is CLOSED (DEC-077): a path to a key it
does not list is refused. So each top level lists the tool's REAL keys, not its documented subset:
`search.query` returns `learning_context` and `history_id` beyond the five its description names.
Items whose shape is the runtime's or open-ended (memory nodes) stay open with `additionalProperties`.
`test_agent_tool_result_schema.py` holds these against each description's `Returns {…}`.

Not here, on purpose: `genesis.message` and `task.complete`, whose results the planner is told not to
reference.
"""
from __future__ import annotations

_S = {"type": "string"}
_B = {"type": "boolean"}
_I = {"type": "integer"}
_ANY: dict = {}
_LIST = {"type": "array"}
_OBJ = {"type": "object"}


def _obj(**properties) -> dict:
    return {"type": "object", "properties": properties}


def _open(**properties) -> dict:
    return {"type": "object", "properties": properties, "additionalProperties": True}


_SEARCH_ITEM = _obj(title=_S, url=_ANY, snippet=_ANY, score=_ANY, metadata=_ANY)

TOOL_RESULTS: dict[str, dict] = {
    "research.query": _obj(raw_result=_S),
    "search.query": _obj(
        query=_S, search_type=_S, results={"type": "array", "items": _SEARCH_ITEM},
        search_score=_ANY, memory=_ANY, learning_context=_ANY, history_id=_ANY,
    ),
    "memory.recall": _obj(
        count=_I,
        nodes={"type": "array", "items": _open(id=_ANY, content=_S, source=_ANY, tags=_ANY, extra=_ANY,
                                               similarity=_ANY)},
    ),
    "memory.write": _obj(node_id=_ANY),
    "content.draft": _obj(
        draft_id=_S, title=_S, body=_S,
        sources_used={"type": "array", "items": _obj(title=_S, url=_ANY, own=_B)},
    ),
    "market.propose": _obj(proposed=_B, key=_ANY, reason=_ANY),
    "leadgen.search": _obj(
        leads={"type": "array", "items": _open(id=_ANY, company=_ANY, url=_ANY, context=_ANY, overall_score=_ANY)},
        count=_I, saved=_B, segment=_ANY, proposed=_LIST,
    ),
    "leadgen.act": _obj(status=_ANY, actions=_LIST, skipped=_LIST, count=_I, dry_run=_B, would_act=_ANY),
    "task.create": _obj(task_id=_ANY, name=_ANY, status=_ANY),
    "arm.analyze": _obj(summary=_ANY, architecture_score=_ANY, integrity_score=_ANY, analysis_id=_ANY),
    "arm.generate": _obj(generated_code=_ANY, explanation=_ANY, generation_id=_ANY),
    "arm.autotune": _obj(status=_ANY, applied=_LIST, skipped=_LIST, log_id=_ANY, dry_run=_B),
    "freelance.optimize_pricing": _obj(status=_ANY, applied=_LIST, recommendations=_LIST, skipped=_LIST,
                                       dry_run=_B, would_change=_ANY),
    "freelance.performance": _obj(signals=_LIST, count=_I),
    "reasoning.evaluate": _obj(available=_B, decision_type=_ANY, reason=_ANY, next_action_title=_ANY,
                               suggested_goal=_ANY, execution_intent=_ANY),
}
