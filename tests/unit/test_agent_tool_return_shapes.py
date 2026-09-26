"""Every agent tool tells the planner what it returns, and the stated keys are the real ones.

Found 2026-09-26 on the FR-46 evidence run (`615b67ea`, runtime 2.24.0 with
`AINDY_PLAN_STEP_REFERENCES=1`). The planner used a step reference, but it gave `memory.write`
`{"$from_step": 0, "path": "results"}`, and step 0 was `research.query`, whose result is
`{"raw_result": ...}` (`results` is `search.query`'s). The runtime refused to resolve it and the
step failed safely. The planner is shown each tool's arguments (FR-33) but never its result, so a
path was a guess. The description is the only channel it has until the runtime renders a result
schema (FR-48), so every description states the return shape, and for each tool that builds its own
result the stated keys are checked against what the tool actually returns.
"""
from __future__ import annotations

import importlib
import re

import pytest

pytestmark = pytest.mark.app_profile

_TOOL_MODULES = (
    "apps.agent.agents.tools",
    "apps.analytics.agents.tools",
    "apps.arm.agents.tools",
    "apps.freelance.agents.tools",
    "apps.masterplan.agents.tools",
    "apps.search.agents.tools",
    "apps.tasks.agents.tools",
)

# Tools whose result is a pass-through the planner should not reach into.
_NOT_REFERENCEABLE = {"task.complete", "genesis.message"}

# Tools that assemble their own result dict: (module, function) -> called with a stubbed syscall.
_SHAPED = {
    "task.create": ("apps.tasks.agents.tools", "task_create"),
    "arm.analyze": ("apps.arm.agents.tools", "arm_analyze"),
    "arm.generate": ("apps.arm.agents.tools", "arm_generate"),
    "arm.autotune": ("apps.arm.agents.tools", "arm_autotune"),
    "freelance.optimize_pricing": ("apps.freelance.agents.tools", "freelance_optimize_pricing"),
    "freelance.performance": ("apps.freelance.agents.tools", "freelance_performance"),
    "leadgen.search": ("apps.search.agents.tools", "leadgen_search"),
    "leadgen.act": ("apps.search.agents.tools", "leadgen_act"),
}


def _app_tools() -> dict[str, dict]:
    from AINDY.agents.tool_registry import TOOL_REGISTRY

    for module_name in _TOOL_MODULES:
        importlib.import_module(module_name).register()
    return {
        name: entry
        for name, entry in TOOL_REGISTRY.items()
        if getattr(entry.get("fn"), "__module__", "").startswith("apps.")
    }


def _stated_keys(description: str) -> set[str]:
    match = re.search(r"[Rr]eturns \{([^}]*)\}", description)
    assert match, description
    return {k.strip().rstrip("[]") for k in match.group(1).split(",") if k.strip()}


def test_every_app_tool_says_what_it_returns():
    missing = []
    for name, entry in sorted(_app_tools().items()):
        description = entry.get("description") or ""
        if name in _NOT_REFERENCEABLE:
            ok = "do not reference its fields" in description
        else:
            ok = re.search(r"[Rr]eturns \{", description) is not None
        if not ok:
            missing.append(name)
    assert not missing, f"tools whose description does not state a return shape: {missing}"


@pytest.mark.parametrize("tool_name", sorted(_SHAPED))
def test_the_stated_keys_are_the_real_keys(tool_name, monkeypatch):
    module_name, fn_name = _SHAPED[tool_name]
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "_dispatch_tool_syscall", lambda *a, **k: {})
    real = set(getattr(module, fn_name)({}, "u-1", None).keys())
    stated = _stated_keys(_app_tools()[tool_name]["description"])
    assert stated == real, f"{tool_name}: description says {sorted(stated)}, tool returns {sorted(real)}"


def test_research_query_returns_raw_result(monkeypatch):
    """The exact case that failed: the description must name the key the syscall really returns."""
    import apps.search.syscalls as syscalls
    import apps.search.services.research_engine as research_engine

    monkeypatch.setattr(research_engine, "web_search", lambda q: "findings")
    result = syscalls._handle_research_query({"query": "q"}, None)
    assert set(result) == {"raw_result"}
    assert _stated_keys(_app_tools()["research.query"]["description"]) == {"raw_result"}
