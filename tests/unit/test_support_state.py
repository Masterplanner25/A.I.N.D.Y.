"""Centralized support-state snapshot (Infinity Support System — Step 1).

Verifies `gather_support_state` assembles the normalized snapshot the orchestrator
consumes, with the exact failure semantics it replaced: memory/metrics/signals
propagate; system_state/goals/task_graph/social_signals fall back to safe
defaults. The dependency-adapter reads + `goals.rank` job are monkeypatched.
"""

from __future__ import annotations

import pytest

import apps.analytics.services.integration.dependency_adapter as adapter
from apps.analytics.services.orchestration import support_state as ss

pytestmark = pytest.mark.app_profile


_SUPPORT_METRICS = {
    "generated_at": "2026-07-08T00:00:00+00:00",
    "window_hours": 24,
    "observability": {
        "requests": {"total": 5, "errors": 1, "error_rate_pct": 20.0, "avg_latency_ms": 12.0},
        "platform_health_status": "degraded",
    },
    "execution": {
        "agent_runs": {"total": 3, "by_status": {"success": 3}},
        "async_jobs": {"total": 0, "by_status": {}},
    },
    "infinity_events": {"recall_used": 2, "score_computed": 1, "next_action_chosen": 1, "total": 4},
}


def _set_happy_fetchers(monkeypatch):
    monkeypatch.setattr(adapter, "fetch_recent_memory", lambda *a, **k: [{"id": "m1"}])
    monkeypatch.setattr(adapter, "fetch_user_metrics", lambda *a, **k: {"x": 1})
    monkeypatch.setattr(adapter, "fetch_memory_signals", lambda **k: [{"type": "failure"}])
    monkeypatch.setattr(adapter, "fetch_system_state", lambda db: {"health_status": "healthy"})
    monkeypatch.setattr(adapter, "fetch_task_graph_context", lambda db, uid: {"ready": [1], "blocked": []})
    monkeypatch.setattr(adapter, "fetch_social_performance_signals", lambda **k: [{"type": "success"}])
    monkeypatch.setattr(adapter, "fetch_search_performance_signals", lambda **k: [{"type": "success"}])
    monkeypatch.setattr(adapter, "fetch_freelance_performance_signals", lambda **k: [{"type": "success"}])
    monkeypatch.setattr(adapter, "fetch_ripple_performance_signals", lambda **k: [{"type": "success"}])
    monkeypatch.setattr(adapter, "fetch_observability_support_metrics", lambda **k: dict(_SUPPORT_METRICS))
    monkeypatch.setattr(ss, "get_job", lambda name: (lambda db, uid, system_state=None: [{"id": "g1"}]))


def test_gather_support_state_assembles_snapshot(monkeypatch):
    _set_happy_fetchers(monkeypatch)
    state = ss.gather_support_state(object(), "u1", "manual")

    assert state.user_id == "u1"
    assert state.memory == [{"id": "m1"}]
    assert state.metrics == {"x": 1}
    assert state.memory_signals == [{"type": "failure"}]
    assert state.system_state == {"health_status": "healthy"}
    assert state.goals == [{"id": "g1"}]
    assert state.task_graph == {"ready": [1], "blocked": []}
    assert state.social_signals == [{"type": "success"}]
    assert state.search_signals == [{"type": "success"}]
    assert state.freelance_signals == [{"type": "success"}]
    assert state.ripple_signals == [{"type": "success"}]
    assert state.support_metrics == _SUPPORT_METRICS


def test_loop_context_shape_matches_orchestrator_contract(monkeypatch):
    _set_happy_fetchers(monkeypatch)
    lc = ss.gather_support_state(object(), "u1", "manual").loop_context
    assert set(lc) == {
        "user_id", "memory", "metrics", "memory_signals",
        "system_state", "goals", "task_graph", "social_signals", "support_metrics",
        "search_signals", "freelance_signals", "ripple_signals",
    }
    assert lc["user_id"] == "u1"
    assert lc["goals"] == [{"id": "g1"}]
    assert lc["support_metrics"] == _SUPPORT_METRICS


def test_summary_counts(monkeypatch):
    _set_happy_fetchers(monkeypatch)
    summary = ss.gather_support_state(object(), "u1", "manual").summary()
    assert summary["memory_count"] == 1
    assert summary["memory_signal_count"] == 1
    assert summary["goal_count"] == 1
    assert summary["ready_task_count"] == 1
    assert summary["blocked_task_count"] == 0
    assert summary["social_signal_count"] == 1
    assert summary["search_signal_count"] == 1
    assert summary["freelance_signal_count"] == 1
    assert summary["ripple_signal_count"] == 1
    assert summary["health_status"] == "healthy"
    assert summary["has_metrics"] is True
    assert summary["platform_health_status"] == "degraded"
    assert summary["infinity_event_total"] == 4


def test_optional_inputs_fall_back_to_defaults(monkeypatch):
    monkeypatch.setattr(adapter, "fetch_recent_memory", lambda *a, **k: [])
    monkeypatch.setattr(adapter, "fetch_user_metrics", lambda *a, **k: None)
    monkeypatch.setattr(adapter, "fetch_memory_signals", lambda **k: [])

    def _boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(adapter, "fetch_system_state", _boom)
    monkeypatch.setattr(adapter, "fetch_task_graph_context", _boom)
    monkeypatch.setattr(adapter, "fetch_social_performance_signals", _boom)
    monkeypatch.setattr(adapter, "fetch_observability_support_metrics", _boom)
    monkeypatch.setattr(ss, "get_job", lambda name: None)  # no goals job registered

    state = ss.gather_support_state(object(), "u1", "manual")
    assert state.system_state == {}
    assert state.goals == []
    assert state.task_graph == {}
    assert state.social_signals == []
    assert state.support_metrics == {}
    assert state.summary()["has_metrics"] is False
    assert state.summary()["platform_health_status"] is None
    assert state.summary()["infinity_event_total"] is None
    assert state.loop_context["support_metrics"] == {}


def test_ripple_signal_failure_does_not_break_the_loop(monkeypatch):
    """RippleTrace is a degradable peripheral; a dead feeder must not stop an Infinity run.

    Asserted separately from the other optional inputs because rippletrace is the only
    feeder that reaches Postgres inside the syscall, so it has more ways to fail than the
    Mongo-backed and HTTP-backed ones.
    """
    _set_happy_fetchers(monkeypatch)

    def _boom(**kwargs):
        raise RuntimeError("rippletrace down")

    monkeypatch.setattr(adapter, "fetch_ripple_performance_signals", _boom)
    state = ss.gather_support_state(object(), "u1", "manual")

    assert state.ripple_signals == []
    assert state.summary()["ripple_signal_count"] == 0
    # Everything else still assembled.
    assert state.social_signals == [{"type": "success"}]
    assert state.goals == [{"id": "g1"}]


def test_goal_ranking_failure_defaults_to_empty(monkeypatch):
    _set_happy_fetchers(monkeypatch)

    def _boom_rank(db, uid, system_state=None):
        raise RuntimeError("rank failed")

    monkeypatch.setattr(ss, "get_job", lambda name: _boom_rank)
    assert ss.gather_support_state(object(), "u1", "manual").goals == []


def test_core_memory_failure_propagates(monkeypatch):
    # memory/metrics/signals are NOT swallowed (matches prior orchestrator behavior)
    def _boom(*a, **k):
        raise RuntimeError("memory store down")

    monkeypatch.setattr(adapter, "fetch_recent_memory", _boom)
    with pytest.raises(RuntimeError):
        ss.gather_support_state(object(), "u1", "manual")


class _FakeDispatcher:
    def __init__(self, envelope):
        self._envelope = envelope
        self.calls = []

    def dispatch(self, name, payload, ctx):
        self.calls.append((name, payload, ctx))
        return self._envelope


def test_fetch_observability_support_metrics_dispatches_syscall(monkeypatch):
    fake = _FakeDispatcher({"status": "success", "data": {"infinity_events": {"total": 4}}})
    monkeypatch.setattr(adapter, "get_dispatcher", lambda: fake)
    sentinel_db = object()

    out = adapter.fetch_observability_support_metrics(
        user_id="u1", db=sentinel_db, window_hours=48
    )

    assert out == {"infinity_events": {"total": 4}}
    (name, payload, ctx) = fake.calls[0]
    assert name == "sys.v1.observability.support_metrics"
    assert payload == {"window_hours": 48}
    assert "execution.read" in ctx.capabilities
    assert str(ctx.user_id) == "u1"
    assert ctx.metadata.get("_db") is sentinel_db


def test_fetch_observability_support_metrics_omits_default_window(monkeypatch):
    fake = _FakeDispatcher({"status": "success", "data": {}})
    monkeypatch.setattr(adapter, "get_dispatcher", lambda: fake)

    adapter.fetch_observability_support_metrics(user_id="u1", db=object())

    # No window_hours passed -> let the runtime apply its default (24h), don't force one.
    assert fake.calls[0][1] == {}


def test_fetch_observability_support_metrics_degrades_on_non_success(monkeypatch):
    # An older runtime without the syscall (or any error envelope) -> empty support signal.
    fake = _FakeDispatcher({"status": "error", "error": "unknown syscall"})
    monkeypatch.setattr(adapter, "get_dispatcher", lambda: fake)

    assert adapter.fetch_observability_support_metrics(user_id="u1", db=object()) == {}
