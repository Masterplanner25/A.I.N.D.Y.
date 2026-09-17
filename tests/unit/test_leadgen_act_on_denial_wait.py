"""`leadgen.act` declares `on_denial="wait"` — the app's phase-3 evidence for AUTHORITY-NEGOTIATION-1.

The runtime's 2.17.0 handoff §3.3 asked for one real tool whose denial we would rather have
parked than failed, so its default flip has a denial to flip on. Taken 2026-09-16 with
`leadgen.act` — the tool that can email a real person (#369). A denial there most plausibly
means the run's 24 h token expired while it sat parked on an approval; failing it would discard
the `leadgen.search` work the run already did.

This pins the declaration and that it stays the *deliberate* one: any other tool that starts
declaring a gate or a variant must be added to the list below on purpose, because each one is
evidence the runtime reads. The behaviour itself (park, typed resume, skip/abort, no grant) is
the runtime's and is tested there; here we only assert what we declared.
"""
from __future__ import annotations

import importlib

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

# The tools that deliberately declare a denial fallback. Extend on purpose, with a reason.
_DECLARED_GATES = {"leadgen.act": "wait"}
_DECLARED_VARIANTS: dict[str, str] = {}


def _app_tools() -> dict[str, dict]:
    from AINDY.agents.tool_registry import TOOL_REGISTRY

    for module_name in _TOOL_MODULES:
        importlib.import_module(module_name).register()
    return {
        name: entry
        for name, entry in TOOL_REGISTRY.items()
        if getattr(entry.get("fn"), "__module__", "").startswith("apps.")
    }


def test_leadgen_act_parks_on_denial():
    entry = _app_tools()["leadgen.act"]
    assert entry["on_denial"] == "wait"
    assert entry["degraded_variant"] is None, "the gate composes after a variant; we declare none"
    assert "parks" in entry["description"], "the planner should be told the step can park"


def test_denial_fallbacks_are_declared_deliberately():
    tools = _app_tools()
    gates = {n: e["on_denial"] for n, e in tools.items() if e.get("on_denial") != "fail"}
    variants = {n: e["degraded_variant"] for n, e in tools.items() if e.get("degraded_variant")}
    assert gates == _DECLARED_GATES, (
        f"a tool declares on_denial without being listed as deliberate evidence: {gates}"
    )
    assert variants == _DECLARED_VARIANTS, (
        f"a tool declares degraded_variant without being listed as deliberate evidence: {variants}"
    )
