"""What a finished agent run found, as text — kept in memory so later runs can recall it.

A plan's steps cannot use each other's results (FR-46), so a planned `memory.write` "summary" is
written before the research it summarises exists. Three runs in a row (2026-09-25/26) saved such a
placeholder; recall then ranked one first (similarity 0.93) and the next run built on nothing. The
owner's call: save the run's ACTUAL findings when it completes, and tell the planner not to fake
them. This module is the digest; `handle_agent_run_completed` saves it.

Mirrors `client/src/utils/runFindings.js` rule for rule (the Collaborator "Continue" digest);
`tests/unit/test_run_findings.py` holds both to the same fixture. Change one, change the other.
"""
from __future__ import annotations

from typing import Any, Iterable

FINDINGS_MARKER = "\n\n--- Findings from the previous run (attached by Collaborator) ---\n"
MAX_FINDINGS_CHARS = 6000
TRUNCATED = "\n[truncated]"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _is_telemetry(node: Any) -> bool:
    return isinstance(node, dict) and str(node.get("source") or "").startswith("system_event:")


def step_findings(tool_name: str, result: Any) -> str | None:
    """One step's findings as text, or None when the step found nothing worth keeping."""
    if not isinstance(result, dict):
        return None
    if tool_name == "research.query":
        return _clean(result.get("raw_result")) or None
    if tool_name == "memory.recall":
        nodes = result.get("nodes") if isinstance(result.get("nodes"), list) else []
        notes = [n for n in nodes if isinstance(n, dict) and not _is_telemetry(n)]
        return "\n".join(f"- {_clean(n.get('content'))}" for n in notes) or None
    if tool_name == "search.query":
        hits = result.get("results") if isinstance(result.get("results"), list) else []
        hits = [h for h in hits if isinstance(h, dict) and (h.get("title") or h.get("snippet"))]
        return "\n".join(
            f"- {_clean(h.get('title'))}"
            + (f": {_clean(h.get('snippet'))}" if h.get("snippet") else "")
            + (f" ({h.get('url')})" if h.get("url") else "")
            for h in hits
        ) or None
    if tool_name == "arm.analyze":
        return _clean(result.get("summary")) or None
    if tool_name == "reasoning.evaluate":
        if not result.get("decision_type"):
            return None
        text = f"Recommendation: {result['decision_type']}"
        if result.get("reason"):
            text += f" (because {result['reason']})"
        if result.get("next_action_title"):
            text += f"\n{_clean(result['next_action_title'])}"
        return text
    if tool_name == "task.create":
        return f"Created task: {_clean(result['name'])}" if result.get("name") else None
    return None


def _referenced_steps(value: Any) -> set[int]:
    """Every `{"$from_step": N}` step index anywhere inside a plan step's args."""
    found: set[int] = set()
    if isinstance(value, dict):
        if "$from_step" in value and isinstance(value.get("$from_step"), int):
            found.add(value["$from_step"])
        for inner in value.values():
            found |= _referenced_steps(inner)
    elif isinstance(value, list):
        for inner in value:
            found |= _referenced_steps(inner)
    return found


def steps_already_saved(plan_steps: Iterable[dict], step_status: dict[int, str]) -> set[int]:
    """Steps whose result a SUCCESSFUL `memory.write` in the same run already stored by reference.

    Owner, 2026-09-26: run `19dcf508` stored step 0's research through
    `memory.write {"content": {"$from_step": 0, …}}`, and the completion hook then saved the same
    research again. The completion hook leaves these out. The references are read from the PLAN's
    args, because the recorded `tool_args` are already resolved. Plan position and `step_index`
    coincide for plans made only of tool steps, which is every plan this app's planner writes.
    """
    saved: set[int] = set()
    for index, step in enumerate(plan_steps or []):
        if not isinstance(step, dict) or step.get("tool") != "memory.write":
            continue
        if str(step_status.get(index) or "").lower() != "success":
            continue
        saved |= _referenced_steps(step.get("args"))
    return saved


def build_findings_digest(steps: Iterable[dict]) -> str:
    """Every successful step's findings, labelled by tool, capped at MAX_FINDINGS_CHARS.

    `steps` are dicts with `tool_name`, `status` and `result` — the shape the steps API returns.
    """
    sections = []
    for step in steps or []:
        if str(step.get("status") or "").lower() != "success":
            continue
        text = step_findings(str(step.get("tool_name") or ""), step.get("result"))
        if text:
            sections.append(f"[{step.get('tool_name')}]\n{text}")
    digest = "\n\n".join(sections)
    if len(digest) > MAX_FINDINGS_CHARS:
        return digest[:MAX_FINDINGS_CHARS] + TRUNCATED
    return digest


def goal_ask(goal: Any) -> str:
    """The owner's words from a goal, without any findings Collaborator attached."""
    text = str(goal or "")
    at = text.find(FINDINGS_MARKER)
    return text if at == -1 else text[:at]
