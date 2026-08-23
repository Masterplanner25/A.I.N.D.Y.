"""End-to-end validation for RippleTrace causal-graph reconstruction.

Evolution Plan (`docs/domains/RIPPLETRACE.md`) — Step 1: prove that a *single
execution* produces reconstructable event **and** memory causality. The
`trace_id` propagation fix means every event in one run shares a single
`trace_id`; these tests assert the app-owned `rippletrace_service` rebuilds the
full event/memory graph for that `trace_id`.

Two angles:
  * ``test_single_trace_reconstructs_event_and_memory_causality`` — deterministic
    construction via the runtime causality APIs (`link_events`,
    `link_event_to_memory`) + direct event rows, then asserts exact
    reconstruction (nodes, edges, root, terminals, dominant path, span, the
    memory-node target, and an async branch).
  * ``test_emit_and_capture_round_trip_is_reconstructable`` — drives the *real*
    emission path (`emit_system_event`) and the *real* memory-capture path
    (`MemoryCaptureEngine.evaluate_and_capture`), then asserts the same graph
    reconstruction — covering `system_event_service` and `memory_capture_engine`.

Runs on the SQLite app-profile harness: `tests/fixtures/db.py` compiles the
Postgres types (JSONB/UUID/Vector) down to SQLite equivalents and disables FK
enforcement, so `system_events` / `event_edges` / `memory_nodes` all persist.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.rippletrace.services import rippletrace_service as rt

pytestmark = pytest.mark.app_profile

_BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _emit_row(db, *, etype, trace_id, user_id, seq, parent=None, payload=None, source="test"):
    """Persist a single SystemEvent row directly (no emission side effects)."""
    from AINDY.db.models.system_event import SystemEvent

    row = SystemEvent(
        id=uuid.uuid4(),
        type=etype,
        user_id=uuid.UUID(user_id),
        trace_id=trace_id,
        parent_event_id=parent,
        source=source,
        payload=payload or {},
        timestamp=_BASE_TS + timedelta(seconds=seq),
    )
    db.add(row)
    db.flush()
    return row


def test_single_trace_reconstructs_event_and_memory_causality(db_session):
    from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
    from AINDY.platform_layer.event_trace_service import link_event_to_memory, link_events

    db = db_session
    trace_id = f"rt-trace-{uuid.uuid4().hex}"
    user_id = str(uuid.uuid4())

    # One execution: a flow run that branches into a memory read and an LLM call,
    # the LLM call deriving a completion. All share one trace_id.
    e1 = _emit_row(db, etype="flow.run", trace_id=trace_id, user_id=user_id, seq=0,
                   payload={"drop_point_id": "drop-xyz"})
    e2 = _emit_row(db, etype="memory.read", trace_id=trace_id, user_id=user_id, seq=1, parent=e1.id)
    e3 = _emit_row(db, etype="llm.call", trace_id=trace_id, user_id=user_id, seq=2, parent=e1.id)
    e4 = _emit_row(db, etype="execution.completed", trace_id=trace_id, user_id=user_id, seq=3, parent=e3.id)

    # Causal edges: a branch off the root (one async child) plus a derived chain.
    link_events(db, e1.id, e2.id, "related_to")
    link_events(db, e1.id, e3.id, "async_child")
    link_events(db, e3.id, e4.id, "derived")

    # Event -> memory causality on the memory-read branch.
    mem = MemoryNodeDAO(db).save(
        content="recalled context for the run",
        source="system_event:memory",
        tags=["causal_memory"],
        user_id=user_id,
        node_type="outcome",
        extra={"trace_id": trace_id},
        generate_embedding=True,
        source_event_id=str(e2.id),
        root_event_id=str(e1.id),
        causal_depth=1,
        impact_score=1.0,
        memory_type="outcome",
    )
    link_event_to_memory(db, e2.id, mem["id"], "stored_as_memory", 1.0)
    db.flush()

    graph = rt.get_trace_graph(db, trace_id)
    events = [n for n in graph["nodes"] if n["node_kind"] == "system_event"]
    memories = [n for n in graph["nodes"] if n["node_kind"] == "memory_node"]
    assert len(events) == 4
    assert len(memories) == 1
    assert len(graph["edges"]) == 4

    # The memory edge is reconstructed as an event -> memory target.
    mem_edges = [e for e in graph["edges"] if e["target_kind"] == "memory_node"]
    assert len(mem_edges) == 1
    assert mem_edges[0]["source"] == str(e2.id)
    assert mem_edges[0]["target"] == str(mem["id"])

    # The async branch is preserved in the reconstructed graph.
    assert any(e["relationship_type"] == "async_child" for e in graph["edges"])

    # Root and terminal reconstruction.
    root = rt.detect_root_event(db, trace_id)
    assert root["id"] == str(e1.id)
    terminal_ids = {t["id"] for t in rt.detect_terminal_events(db, trace_id)}
    assert str(e4.id) in terminal_ids       # leaf of the derived chain
    assert str(e1.id) not in terminal_ids   # the root is never terminal

    # Span metrics over the whole graph (events + memory).
    span = rt.calculate_ripple_span(db, trace_id)
    assert span["node_count"] == 5
    assert span["edge_count"] == 4
    assert span["depth"] >= 2
    assert span["terminal_count"] >= 1

    # Dominant path starts at the root and is a longest causal chain.
    path = rt.detect_dominant_path(db, trace_id)
    assert path[0]["id"] == str(e1.id)
    assert len(path) >= 3

    # count_trace_events is user-scoped.
    assert rt.count_trace_events(db, trace_id, user_id) == 4
    assert rt.count_trace_events(db, trace_id, str(uuid.uuid4())) == 0


def test_emit_and_capture_round_trip_is_reconstructable(db_session):
    from AINDY.core.system_event_service import emit_system_event
    from AINDY.memory.memory_capture_engine import MemoryCaptureEngine
    from AINDY.platform_layer.event_trace_service import link_events

    db = db_session
    trace_id = f"rt-emit-{uuid.uuid4().hex}"
    user_id = str(uuid.uuid4())

    # Real emission path. Non-"execution.*" types avoid the execution-contract
    # gate while still exercising emit_system_event end to end.
    root_id = emit_system_event(
        db=db, event_type="rippletrace.test.root", user_id=user_id,
        trace_id=trace_id, source="test", payload={"step": "root"},
    )
    child_id = emit_system_event(
        db=db, event_type="rippletrace.test.child", user_id=user_id,
        trace_id=trace_id, parent_event_id=root_id, source="test", payload={"step": "child"},
    )
    assert root_id and child_id
    link_events(db, root_id, child_id, "derived")

    # Real memory-capture path: synchronous because no pipeline is active.
    captured = MemoryCaptureEngine(db, user_id, "system").evaluate_and_capture(
        event_type="execution.completed",
        content="captured outcome",
        source="system_event:test",
        extra={"trace_id": trace_id, "source_event_id": str(child_id)},
        force=True,
    )
    assert captured and captured.get("id")
    db.flush()

    graph = rt.get_trace_graph(db, trace_id)
    event_ids = {n["id"] for n in graph["nodes"] if n["node_kind"] == "system_event"}
    assert str(root_id) in event_ids
    assert str(child_id) in event_ids

    # Event -> memory causality was captured and is reconstructable.
    mem_edges = [e for e in graph["edges"] if e["target_kind"] == "memory_node"]
    assert any(e["source"] == str(child_id) for e in mem_edges)
    memory_nodes = [n for n in graph["nodes"] if n["node_kind"] == "memory_node"]
    assert any(n["id"] == captured["id"] for n in memory_nodes)

    # A single trace_id ties the whole execution together.
    assert rt.count_trace_events(db, trace_id, user_id) >= 2
