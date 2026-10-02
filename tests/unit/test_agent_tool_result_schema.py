"""Every referenceable agent tool declares what it returns, and the planner's references are held to it.

Runtime 2.25.0 (FR-48): `register_tool(..., result_schema=...)` puts `returns={...}` on the planner's
catalog line, and with step references on, each `{"$from_step": N, "path": …}` is checked against step
N's schema at plan time. Run `615b67ea` (2026-09-26) gave `memory.write` `{"$from_step": 0, "path":
"results"}` where step 0 was `research.query`, which returns `{"raw_result": …}`: the research ran and
was paid for before step 2 failed. That plan is now refused before anything runs.

A schema that lists `properties` is closed, so a declaration missing a real key would refuse a correct
reference. Each declaration therefore carries at least the keys the tool's description states, and the
tools that shape their own result declare exactly what they return.
"""
from __future__ import annotations

import importlib
import re

import pytest

pytestmark = pytest.mark.app_profile

from tests.unit.test_agent_tool_return_shapes import _ARGS, _NOT_REFERENCEABLE, _SHAPED, _app_tools, _stated_keys  # noqa: E402


def _declared_keys(entry: dict) -> set[str]:
    return set(((entry.get("result_schema") or {}).get("properties") or {}).keys())


def test_every_referenceable_tool_declares_a_result_schema():
    missing = sorted(name for name, entry in _app_tools().items()
                     if name not in _NOT_REFERENCEABLE and not entry.get("result_schema"))
    assert not missing, f"tools a later step may reference, with no result_schema (FR-48): {missing}"


@pytest.mark.parametrize("tool_name", sorted(t for t in _app_tools() if t not in _NOT_REFERENCEABLE))
def test_the_declaration_carries_every_key_the_description_states(tool_name):
    entry = _app_tools()[tool_name]
    stated = _stated_keys(entry["description"])
    assert stated <= _declared_keys(entry), (
        f"{tool_name}: description states {sorted(stated)}, result_schema declares {sorted(_declared_keys(entry))}; "
        "a closed schema refuses a reference to any key it does not list"
    )


@pytest.mark.parametrize("tool_name", sorted(_SHAPED))
def test_a_tool_that_shapes_its_result_declares_exactly_those_keys(tool_name, monkeypatch):
    module_name, fn_name = _SHAPED[tool_name]
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "_dispatch_tool_syscall", lambda *a, **k: {})
    real = set(getattr(module, fn_name)(dict(_ARGS.get(tool_name, {})), "u-1", None).keys())
    assert _declared_keys(_app_tools()[tool_name]) == real


def test_run_615b67ea_is_refused_at_plan_time_and_the_right_path_is_not():
    from AINDY.agents.step_references import validate_plan_references

    _app_tools()  # registers our tools, schemas included

    def plan(path):
        return {"steps": [
            {"tool": "research.query", "args": {"query": "AI search"}},
            {"tool": "memory.write", "args": {"content": {"$from_step": 0, "path": path}}},
        ]}

    errors = validate_plan_references(plan("results"))
    assert errors and any("results" in e for e in errors), errors
    assert validate_plan_references(plan("raw_result")) == []
    # The writing step's documented hand-off: recalled nodes into content.draft.
    assert validate_plan_references({"steps": [
        {"tool": "memory.recall", "args": {"query": "q"}},
        {"tool": "content.draft", "args": {"brief": "b", "sources": {"$from_step": 0, "path": "nodes"}}},
    ]}) == []
    assert not re.search(r"\bnodes\b", " ".join(validate_plan_references({"steps": [
        {"tool": "memory.recall", "args": {"query": "q"}},
        {"tool": "content.draft", "args": {"brief": "b", "sources": {"$from_step": 0, "path": "nodes.0.content"}}},
    ]})))
