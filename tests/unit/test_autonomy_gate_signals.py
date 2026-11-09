"""The autonomy gate sees the system it is gating (audit 2026-11-01 D3, owner 2026-11-08).

In production the runtime runs the trigger evaluator in a callback subprocess, and the extension boundary redacts the DB
session on the way in, so the evaluator never computed health, load or failures: every decision was `execute`. The fix
computes the signals in the caller's process (`gate_signals`, through the shared `gate`) and passes them as data.
These tests cross the real boundary (`sanitize_extension_context`) the way production does.
"""
from __future__ import annotations

import json

import pytest

from AINDY.platform_layer.extension_boundary import sanitize_extension_context
from apps.agent.agents import triggers

pytestmark = pytest.mark.app_profile

TRIGGER = {"trigger_type": "schedule", "source": "scheduler.masterplan_eta", "goal": "daily_eta_recalculation",
           "importance": 0.55}


def _across_the_boundary(context):
    """What the evaluator receives in its subprocess: the payload after the extension boundary."""
    payload = sanitize_extension_context({"trigger_type": "schedule", "trigger": TRIGGER, "context": context})
    return triggers.evaluate_autonomy_trigger(payload)


@pytest.fixture
def critical(monkeypatch):
    monkeypatch.setattr(triggers, "compute_current_state",
                        lambda db: {"health_status": "critical", "system_load": 0.2, "failure_rate": 0.4})
    monkeypatch.setattr(triggers, "get_relevant_memories", lambda query, db=None: [])
    monkeypatch.setattr(triggers, "get_recent_ripple_patterns", lambda db, user_id=None: [])


def test_before_the_fix_a_critical_system_still_executed(db_session, critical):
    """The old path: only the session in the context. It is redacted at the boundary, so no signal is built."""
    decision = _across_the_boundary({"db": db_session, "user_id": None})
    assert decision["decision"] == "execute"


def test_with_signals_computed_here_a_critical_system_defers(db_session, critical):
    signals = triggers.gate_signals(db=db_session, trigger=TRIGGER, context={"goal_alignment": 0.65})
    json.dumps(signals)  # plain data: nothing for the boundary to redact
    assert "db" not in signals and signals["system_state"]["health_status"] == "critical"
    decision = _across_the_boundary({**signals, "db": db_session})
    assert decision["decision"] == "defer" and "critical" in decision["reason"]


def test_a_repeated_failure_pattern_defers_a_scheduled_job(db_session, monkeypatch):
    monkeypatch.setattr(triggers, "compute_current_state", lambda db: {"health_status": "healthy"})
    monkeypatch.setattr(triggers, "get_relevant_memories", lambda query, db=None: [])
    monkeypatch.setattr(triggers, "get_recent_ripple_patterns",
                        lambda db, user_id=None: [{"trace_id": "t", "failure_events": 3, "repeated_failure": True}])
    signals = triggers.gate_signals(db=db_session, trigger=TRIGGER, context={"goal_alignment": 0.65})
    assert _across_the_boundary(signals)["decision"] == "defer"


def test_importance_is_read_from_the_trigger():
    base = {"trigger_type": "schedule", "context": {"system_state": {"health_status": "healthy"}, "goal_alignment": 0.5}}
    low = triggers.evaluate_autonomy_trigger({**base, "trigger": {"importance": 0.1}})
    high = triggers.evaluate_autonomy_trigger({**base, "trigger": {"importance": 0.9}})
    assert high["priority"] > low["priority"]


def test_the_signals_job_is_registered():
    from AINDY.platform_layer.registry import get_job

    assert get_job("autonomy.signals") is triggers.gate_signals


@pytest.mark.parametrize("module, job, work", [
    ("apps.tasks.bootstrap", "_scheduler_check_task_recurrence", "apps.tasks.services.task_service.handle_recurrence"),
    ("apps.masterplan.bootstrap", "_scheduler_recalculate_all_etas", "apps.masterplan.services.eta_service.recalculate_all_etas"),
    ("apps.analytics.bootstrap", "_scheduler_recalculate_all_scores", None),
])
def test_each_scheduled_job_gates_with_its_importance_and_honours_a_defer(module, job, work, monkeypatch):
    import importlib

    import apps._shared.autonomy as autonomy

    seen = {}

    def fake_gate(db, *, trigger, context=None, user_id=None):
        seen["trigger"] = dict(trigger)
        return {"decision": "defer", "priority": 0.1, "reason": "test defer", "defer_seconds": 300}

    monkeypatch.setattr(autonomy, "gate", fake_gate)
    import AINDY.agents.autonomous_controller as controller

    monkeypatch.setattr(controller, "record_decision", lambda **kw: None)  # the job's own session; not under test
    if work:
        mod_name, attr = work.rsplit(".", 1)
        monkeypatch.setattr(importlib.import_module(mod_name), attr,
                            lambda *a, **k: pytest.fail("the work ran though the gate deferred"))
    getattr(importlib.import_module(module), job)()
    assert seen["trigger"]["trigger_type"] == "schedule"
    assert isinstance(seen["trigger"].get("importance"), float)  # where the evaluator reads it
