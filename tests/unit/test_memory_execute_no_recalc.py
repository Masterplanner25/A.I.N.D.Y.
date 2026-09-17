"""A memory-loop execution must not recalculate the Infinity score — MEMORY-EXECUTE-LATENCY-1.

`memory_execution_orchestrate` was the terminal node of `memory_execute_loop`, the graph
`POST /memory/execute` runs. It ran the full Infinity loop synchronously on the request path —
GENESIS-TURN-LATENCY-1's defect in a second flow. The Genesis precedent went async (#263) and
then away (#294): a turn is not a scoring event. A memory-loop execution runs a `leadgen` search
or a `genesis_message` and changes nothing the score reads, so it is the same call, and the path
had never executed anyway.

Until runtime 2.20.0 the graph was runtime-owned and registered BEFORE plugins, so the app could
drop the node from its own `memory_execution` graph but not from the one the route actually
runs — the node survived as a pass-through and FR-32 asked the runtime to give the graph up.
2.20.0 shipped option 2: the runtime's shape is a DEFAULT registered last, a plugin's wins. This
app now registers `memory_execute_loop` itself, ending at `memory_execution_run`, and the
orchestrate node is deleted. These tests pin that the node is gone, that both graphs and the
plan end at `run`, and that our registration is the one the runtime's default defers to.
"""
from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.app_profile

flow_definitions = pytest.importorskip("apps.automation.flows.flow_definitions")

_END_AT_RUN = {
    "start": "memory_execution_validate",
    "edges": {"memory_execution_validate": ["memory_execution_run"]},
    "end": ["memory_execution_run"],
}


def test_the_orchestrate_node_is_gone():
    from AINDY.runtime.flow_engine import NODE_REGISTRY

    assert not hasattr(flow_definitions, "memory_execution_orchestrate")
    assert "memory_execution_orchestrate" not in NODE_REGISTRY
    src = inspect.getsource(flow_definitions)
    assert '@register_node("memory_execution_orchestrate")' not in src


def test_both_graphs_end_at_run_and_never_orchestrate():
    from AINDY.runtime.flow_engine import FLOW_REGISTRY

    flow_definitions.register_all_flows()
    for name in ("memory_execution", "memory_execute_loop"):
        graph = FLOW_REGISTRY[name]
        assert graph["start"] == _END_AT_RUN["start"], name
        assert graph["edges"] == _END_AT_RUN["edges"], name
        assert graph["end"] == _END_AT_RUN["end"], name


def test_the_plan_ends_at_run():
    from apps.automation import bootstrap as auto_bootstrap

    plan = inspect.getsource(auto_bootstrap)
    assert '["memory_execution_validate", "memory_execution_run"]' in plan
    assert "memory_execution_orchestrate" not in plan


def test_no_infinity_recalc_is_reachable_from_the_memory_flow():
    """Guards the behaviour on the nodes that remain: no execute_infinity, no recalc job, no trigger."""
    for node in (flow_definitions.memory_execution_validate, flow_definitions.memory_execution_run):
        code = inspect.getsource(node)
        assert "execute_infinity" not in code, node.__name__
        assert "infinity_recalc" not in code, node.__name__
        assert "job.submit" not in code, node.__name__
        assert "trigger_event" not in code, node.__name__


def test_our_registration_wins_over_the_runtime_default():
    """FR-32 option 2 (runtime 2.20.0): `register_default_memory_execute_loop()` defers to a plugin's graph.

    Boot order on both the API and the worker is runtime flows → plugin flows → runtime DEFAULTS,
    so by the time the default asks `"memory_execute_loop" in FLOW_REGISTRY` ours is there. This
    reproduces that order and asserts the default reports it stood down and the graph is ours.
    """
    from AINDY.runtime.flow_definitions import register_all_flows as runtime_register_all_flows
    from AINDY.runtime.flow_definitions_memory import (
        DEFAULT_MEMORY_EXECUTE_LOOP,
        register_default_memory_execute_loop,
    )
    from AINDY.runtime.flow_engine import FLOW_REGISTRY

    runtime_register_all_flows()
    flow_definitions.register_all_flows()
    assert register_default_memory_execute_loop() is False, "the runtime default must defer to ours"
    graph = FLOW_REGISTRY["memory_execute_loop"]
    assert graph["end"] == ["memory_execution_run"]
    # and the default we displaced is the three-node shape that scored — so the win is meaningful
    assert DEFAULT_MEMORY_EXECUTE_LOOP["end"] == ["memory_execution_orchestrate"]
    assert graph != DEFAULT_MEMORY_EXECUTE_LOOP
