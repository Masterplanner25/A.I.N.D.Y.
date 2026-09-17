"""Our conditional edges are named predicates, not lambdas — runtime #680 (2.17.0), taken 2026-09-16.

`{"target": …, "condition": <lambda>}` kept the decision out of the flow's graph signature, so a
run parked across a deploy could resume into a decision it was never planned for
(`FLOW-GRAPH-SIGNATURE-1`). `{"target": …, "when": "<name>"}` puts the name in the signature and
fails loudly at resolution if the name is missing. This repo had exactly seven lambdas in three
places: `genesis_conversation`'s synthesis gate, and the `watcher_evaluate_trigger` switch
declared twice (automation and tasks). Converted in one pass because zero runs had ever been
recorded on either flow, so the per-flow drain the conversion otherwise needs was empty.

Three things pinned: no `condition` lambda is left anywhere under `apps/`; each named edge
resolves to a registered predicate and routes the way the lambda did; and the flow signatures now
carry the decision names (the reason for doing this at all).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

APPS = Path(__file__).resolve().parents[2] / "apps"


def test_no_condition_lambdas_remain_under_apps():
    offenders = [
        f"{path.relative_to(APPS.parent)}:{n}"
        for path in APPS.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r'"condition"\s*:\s*lambda', line)
    ]
    assert not offenders, (
        "conditional edges must name a registered predicate (`when`), not carry a lambda — "
        f"the lambda keeps the decision out of the graph signature: {offenders}"
    )


def _watcher_flow() -> dict:
    from AINDY.runtime.flow_engine import FLOW_REGISTRY

    # Either declaring module registers it; import both so the predicates are bound either way.
    import apps.automation.flows.watcher_flows  # noqa: F401
    import apps.tasks.flows.tasks_flows  # noqa: F401

    if "watcher_evaluate_trigger" not in FLOW_REGISTRY:
        apps.automation.flows.watcher_flows.register()
    return FLOW_REGISTRY["watcher_evaluate_trigger"]


@pytest.mark.parametrize(
    "decision, expected_target",
    [
        ("execute", "watcher_ingest_validate"),
        ("defer", "watcher_defer_job_node"),
        ("ignore", "watcher_ignore_node"),
        (None, "watcher_ignore_node"),
    ],
)
def test_watcher_switch_routes_exactly_as_the_lambdas_did(decision, expected_target):
    from AINDY.runtime.flow_engine.node_executor import resolve_next_node

    flow = _watcher_flow()
    state = {"watcher_decision": decision} if decision is not None else {}
    assert resolve_next_node("watcher_record_decision_node", state, flow) == expected_target


def test_watcher_switch_edges_are_named_and_registered():
    from AINDY.runtime.flow_engine import DEFAULT_PREDICATE, PREDICATE_REGISTRY

    edges = _watcher_flow()["edges"]["watcher_record_decision_node"]
    names = [edge["when"] for edge in edges]
    assert names == ["watcher_execute", "watcher_defer", DEFAULT_PREDICATE]
    assert all(name in PREDICATE_REGISTRY for name in names)
    assert not any("condition" in edge for edge in edges)


def test_genesis_synthesis_gate_is_named_and_routes():
    from AINDY.runtime.flow_engine import FLOW_REGISTRY, PREDICATE_REGISTRY
    from AINDY.runtime.flow_engine.node_executor import resolve_next_node
    from apps.automation.flows import flow_definitions

    if "genesis_conversation" not in FLOW_REGISTRY:
        flow_definitions.register_all_flows()
    flow = FLOW_REGISTRY["genesis_conversation"]
    (edge,) = flow["edges"]["genesis_record_exchange"]
    assert edge == {"when": "genesis_synthesis_ready", "target": "genesis_store_synthesis"}
    assert "genesis_synthesis_ready" in PREDICATE_REGISTRY

    node = "genesis_record_exchange"
    assert resolve_next_node(node, {"synthesis_ready": True}, flow) == "genesis_store_synthesis"
    assert resolve_next_node(node, {"event": {"synthesis_ready": True}}, flow) == "genesis_store_synthesis"
    # Not ready: no edge matches, the WAIT/RESUME contract keeps the run on this node.
    assert resolve_next_node(node, {"synthesis_ready": False}, flow) is None
    assert resolve_next_node(node, {}, flow) is None


def test_signatures_now_carry_the_decision_names():
    """The point of the migration: the decision is part of the graph identity."""
    from AINDY.runtime.flow_engine import FLOW_REGISTRY
    from AINDY.runtime.flow_engine.graph_signature import _canonical_edges

    watcher = _canonical_edges(_watcher_flow()["edges"])["watcher_record_decision_node"]
    assert [e["when"] for e in watcher if isinstance(e, dict)] == [
        "watcher_execute", "watcher_defer", "default",
    ]
    genesis = _canonical_edges(FLOW_REGISTRY["genesis_conversation"]["edges"])["genesis_record_exchange"]
    assert genesis == [{"target": "genesis_store_synthesis", "when": "genesis_synthesis_ready"}]
