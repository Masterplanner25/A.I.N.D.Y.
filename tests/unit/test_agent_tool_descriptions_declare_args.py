"""Every agent tool's description carries its argument contract — because nothing else does.

Found 2026-09-16 by approving seven agent runs parked since the 2.13.0 governor checks: all four
that planned `arm.analyze` failed with `sys.v1.arm.analyze requires 'file_path'`. The planner had
sent `{"topic": ...}`, because the tool's description said "Analyze code or a topic" and that
one line is the ONLY thing the planner ever sees of a tool. The runtime renders the catalog as
`- name: description (risk=...)` (`agent_runtime/planning.py`), `register_tool` has no argument
schema parameter, and the Claude planner's `submit_plan` schema declares `args: {type: object}`
free-form. Four of the sixteen tools already wrote `Args: {...}` into their description; the
other ten did not, and one of those lied about what it takes.

Until the runtime grows `register_tool(args_schema=...)` (filed as an FR), the description IS
the contract, so this test makes the convention load-bearing: every tool this repo registers
must say `Args:`, and `arm.analyze` must not invite a topic.
"""
from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.app_profile

# The seven modules that call `register_tool`. Registration is a dict write, so calling
# `register()` again in a process that already booted the app profile is harmless.
_TOOL_MODULES = (
    "apps.agent.agents.tools",
    "apps.analytics.agents.tools",
    "apps.arm.agents.tools",
    "apps.freelance.agents.tools",
    "apps.masterplan.agents.tools",
    "apps.search.agents.tools",
    "apps.tasks.agents.tools",
)


def _app_tools() -> dict[str, dict]:
    from AINDY.agents.tool_registry import TOOL_REGISTRY

    for module_name in _TOOL_MODULES:
        importlib.import_module(module_name).register()
    return {
        name: entry
        for name, entry in TOOL_REGISTRY.items()
        if getattr(entry.get("fn"), "__module__", "").startswith("apps.")
    }


def test_every_app_tool_description_declares_its_args():
    tools = _app_tools()
    # 15, not the "16 live tools" figure: the sixteenth is the runtime's own `runtime.selftest`
    # (`platform_layer/runtime_agent_defaults.py`), which is not ours to describe.
    assert len(tools) == 15, sorted(tools)

    missing = sorted(name for name, entry in tools.items() if "Args:" not in entry["description"])
    assert not missing, (
        "these tools give the planner no argument contract — the description line is the only "
        f"channel it has, so a guessed key fails the step at execution: {missing}"
    )


def test_arm_analyze_asks_for_a_file_not_a_topic():
    """The exact mismatch that failed four runs: the syscall requires `file_path`."""
    description = _app_tools()["arm.analyze"]["description"]
    assert "file_path" in description
    assert "or a topic" not in description
