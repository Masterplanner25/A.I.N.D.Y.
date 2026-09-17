"""Every agent tool declares its argument contract as `args_schema` — the planner's only channel.

Found 2026-09-16 by approving seven agent runs parked since the 2.13.0 governor checks: all four
that planned `arm.analyze` failed with `sys.v1.arm.analyze requires 'file_path'`. The planner had
sent `{"topic": ...}`, because the tool's description said "Analyze code or a topic" and that one
line was the ONLY thing the planner ever saw of a tool. Until 2.20.0 the description carried an
`Args: {...}` block by convention and this file made the convention load-bearing (FR-33 asked for
a real channel). 2.20.0 shipped it: `register_tool(..., args_schema={...})` in the dispatcher's
dialect (`required` + `properties[].type`), rendered into the catalog as `args={…}` and checked
before dispatch under `AINDY_TOOL_ARGS_VALIDATION` (`warn` today; `enforce` once the counter reads
zero invalid on the live stack). The prose is gone; the schema is the contract, and this file pins
it the same way: every tool this repo registers declares one, the declaration is one the validator
can act on, and `arm.analyze` still cannot be handed a topic.
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

# What `syscall_versioning._SCHEMA_TYPE_MAP` honours. A type outside this set is skipped by the
# validator silently, which would make a declaration look enforced when it is not.
_VALIDATOR_TYPES = {"string", "str", "int", "integer", "float", "number", "bool", "boolean", "list", "array", "dict", "object"}


def _app_tools() -> dict[str, dict]:
    from AINDY.agents.tool_registry import TOOL_REGISTRY

    for module_name in _TOOL_MODULES:
        importlib.import_module(module_name).register()
    return {
        name: entry
        for name, entry in TOOL_REGISTRY.items()
        if getattr(entry.get("fn"), "__module__", "").startswith("apps.")
    }


def test_every_app_tool_declares_an_args_schema():
    tools = _app_tools()
    # 15, not the "16 live tools" figure: the sixteenth is the runtime's own `runtime.selftest`
    # (`platform_layer/runtime_agent_defaults.py`), which is not ours to describe.
    assert len(tools) == 15, sorted(tools)

    missing = sorted(name for name, entry in tools.items() if not isinstance(entry.get("args_schema"), dict))
    assert not missing, (
        "these tools give the planner no argument contract — the schema is the only channel it "
        f"has, so a guessed key fails the step at execution: {missing}"
    )


def test_every_declared_schema_is_one_the_validator_can_act_on():
    """`required` names declared properties (the runtime refuses otherwise, at registration), and
    every typed property uses a spelling the dispatcher's validator honours."""
    from AINDY.agents.tool_registry import tool_args_schema

    for name in _app_tools():
        schema = tool_args_schema(name)
        assert schema is not None, name
        props = schema.get("properties")
        assert isinstance(props, dict), f"{name}: properties must be a dict"
        req = schema.get("required")
        assert isinstance(req, list), f"{name}: required must be a list (empty is fine)"
        assert set(req) <= set(props), f"{name}: required {req} not all declared under properties"
        for prop, spec in props.items():
            assert isinstance(spec, dict), f"{name}.{prop}: property spec must be a dict"
            if "type" in spec:
                assert spec["type"] in _VALIDATOR_TYPES, f"{name}.{prop}: type {spec['type']!r} is not one the validator checks"


def test_the_prose_convention_is_retired():
    """The `Args: {…}` block was the workaround; two contracts drift. The schema is the one."""
    tools = _app_tools()
    still_prose = sorted(name for name, entry in tools.items() if "Args:" in (entry.get("description") or ""))
    assert not still_prose, f"the description should describe; the schema declares: {still_prose}"


def test_arm_analyze_asks_for_a_file_not_a_topic():
    """The exact mismatch that failed four runs: the syscall requires `file_path`, and the
    validator must say so before dispatch when the planner guesses `topic`."""
    from AINDY.agents.tool_registry import tool_args_schema, validate_tool_args

    schema = tool_args_schema("arm.analyze")
    assert schema["required"] == ["file_path"]
    assert "topic" not in schema["properties"]
    assert "or a topic" not in _app_tools()["arm.analyze"]["description"]

    errors = validate_tool_args("arm.analyze", {"topic": "cost governor phase 2"})
    assert any("file_path" in e for e in errors), errors
    assert validate_tool_args("arm.analyze", {"file_path": "apps/arm/agents/tools.py"}) == []


def test_the_catalog_line_carries_the_schema():
    """What the planner actually reads: the runtime renders `args={…}` from the registry when a
    tool dict does not carry the key — and our run-tool provider's dicts do not."""
    import json

    from AINDY.agents.agent_runtime import planning

    _app_tools()
    line = planning._catalog_line({"name": "arm.analyze", "description": "x", "risk": "medium"})
    assert " args=" in line
    rendered = json.loads(line.split(" args=", 1)[1])
    assert rendered["required"] == ["file_path"]
