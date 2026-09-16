"""A memory-loop execution must not recalculate the Infinity score — MEMORY-EXECUTE-LATENCY-1.

`memory_execution_orchestrate`, the terminal node of both `memory_execute_loop` (runtime-owned
graph) and `memory_execution` (ours), ran the full Infinity loop synchronously on the
`POST /memory/execute` request path — GENESIS-TURN-LATENCY-1's defect in a second flow. The
Genesis precedent went async (#263) and then away (#294): a turn is not a scoring event. A
memory-loop execution runs a `leadgen` search or a `genesis_message` and changes nothing the
score reads, so it is the same call, and the path had never executed anyway.

The node function stays registered because the runtime's `memory_execute_loop` graph names it
(registered before plugins load — the app cannot drop it from that graph without overriding a
runtime-owned name; FR-32). These tests pin that it no longer scores, that our own graph and plan
no longer include it, and that the runtime's graph still resolves every node it names.
"""
from __future__ import annotations

import ast
import inspect

import pytest

pytestmark = pytest.mark.app_profile

flow_definitions = pytest.importorskip("apps.automation.flows.flow_definitions")


def test_the_node_does_not_dispatch_anything(monkeypatch):
    calls: list = []
    monkeypatch.setattr(flow_definitions, "_syscall_data", lambda *a, **k: calls.append(a) or {})

    out = flow_definitions.memory_execution_orchestrate(
        {"original_workflow": "leadgen", "memory_execution_response": {"result": {"ok": True}}},
        {"user_id": "u", "db": None},
    )
    assert calls == []
    assert out["status"] == "SUCCESS"
    resp = out["output_patch"]["memory_execution_response"]
    assert resp["result"] == {"ok": True}  # the caller's response is passed through intact
    assert resp["orchestration"] is None
    assert resp["orchestration_skipped"] == "not_a_scoring_event"


def _body_without_docstring(fn) -> str:
    tree = ast.parse(inspect.getsource(fn))
    body = tree.body[0].body
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
        body = body[1:]  # the docstring records the history and is allowed to name it
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_no_infinity_recalc_is_reachable_from_the_memory_flow():
    """Guards the behaviour, not the old body: no execute_infinity, no recalc job, no memory trigger."""
    code = _body_without_docstring(flow_definitions.memory_execution_orchestrate)
    assert "execute_infinity" not in code
    assert "infinity_recalc" not in code
    assert "job.submit" not in code
    assert "trigger_event" not in code


def test_our_graph_and_plan_end_at_run():
    from apps.automation import bootstrap as auto_bootstrap

    src = inspect.getsource(flow_definitions)
    assert '"memory_execution_run": ["memory_execution_orchestrate"]' not in src
    assert '"end": ["memory_execution_run"]' in src
    plan = inspect.getsource(auto_bootstrap)
    assert '["memory_execution_validate", "memory_execution_run"]' in plan
    assert "memory_execution_orchestrate" not in plan


def test_the_runtime_graph_still_resolves_its_terminal_node():
    """Until FR-32 lands, the runtime's `memory_execute_loop` names our node; it must exist."""
    from AINDY.runtime.flow_definitions import register_all_flows
    from AINDY.runtime.flow_engine import FLOW_REGISTRY, NODE_REGISTRY

    register_all_flows()  # the runtime's registration; our nodes registered on import via @register_node
    graph = FLOW_REGISTRY["memory_execute_loop"]
    for node in graph["end"]:
        assert node in NODE_REGISTRY, f"runtime graph names {node!r}; the app must keep it registered"
