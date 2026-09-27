"""A pending task that is not yet due is left out of the two completion ratios.

Owner's call, 2026-09-26 (option B). decision_efficiency and masterplan_progress were both
completed ÷ all tasks, so planning work read as missing it: that day's agent runs added 15 pending
tasks (11 not yet due) and the master score fell 54.9 → 39.1 with nothing late.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.analytics.services.scoring import infinity_service as svc

pytestmark = pytest.mark.app_profile

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _task(status, due=None):
    return {"status": status, "due_date": due.isoformat() if due else None, "end_time": None}


def test_only_a_pending_task_with_a_future_due_date_is_not_yet_due():
    assert svc._not_yet_due(_task("pending", NOW + timedelta(days=3)), NOW) is True
    assert svc._not_yet_due(_task("pending", NOW - timedelta(days=1)), NOW) is False  # overdue counts
    assert svc._not_yet_due(_task("pending"), NOW) is False  # open-ended work counts
    assert svc._not_yet_due(_task("in_progress", NOW + timedelta(days=3)), NOW) is False  # started counts
    assert svc._not_yet_due(_task("completed", NOW + timedelta(days=3)), NOW) is False


def test_a_naive_due_date_is_read_as_utc():
    naive = {"status": "pending", "due_date": "2026-09-30T00:00:00"}
    assert svc._not_yet_due(naive, NOW) is True


def _stub(monkeypatch, tasks):
    import apps.arm.public as arm_public

    monkeypatch.setattr(svc, "_get_user_tasks_for_scoring", lambda user_id, db: tasks)
    monkeypatch.setattr(arm_public, "get_analysis_quality_signals",
                        lambda user_id, db, window_days: {"quality_avg": 0.0, "usage_count": 0})


def test_decision_efficiency_ignores_planned_work_that_is_not_due(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(days=5)
    done = [_task("completed") for _ in range(4)]
    planned = [_task("pending", future) for _ in range(11)]
    open_ended = [_task("pending") for _ in range(4)]
    _stub(monkeypatch, done + planned + open_ended)
    score, _ = svc.calculate_decision_efficiency("u-1", None)
    # 4 / (4 + 4): the 11 not-yet-due tasks are out; completion_rate 0.5 × 60 = 30, ARM 0
    assert score == pytest.approx(30.0)


def test_decision_efficiency_counts_them_once_they_fall_due(monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    tasks = [_task("completed") for _ in range(4)] + [_task("pending", past) for _ in range(11)]
    _stub(monkeypatch, tasks)
    score, _ = svc.calculate_decision_efficiency("u-1", None)
    assert score == pytest.approx(round(4 / 15 * 60, 2))


def test_masterplan_progress_ignores_planned_work_that_is_not_due(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(days=5)
    tasks = [_task("completed") for _ in range(4)] + [_task("pending", future) for _ in range(11)] + [_task("pending")]

    class _Plan:
        id = 10
        days_ahead_behind = None

    class _Query:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _Plan()

    class _DB:
        def query(self, *_a):
            return _Query()

    class _MasterPlan:
        user_id = None
        is_active = type("C", (), {"is_": staticmethod(lambda v: True)})()

    monkeypatch.setattr(svc, "get_symbol", lambda name: _MasterPlan if name == "MasterPlan" else None)
    monkeypatch.setattr(svc, "_get_user_tasks_for_scoring", lambda user_id, db: tasks)
    monkeypatch.delenv("AINDY_MASTERPLAN_GOAL_ATTAINMENT", raising=False)  # live formula, not the blend
    score, _ = svc.calculate_masterplan_progress("u-1", _DB())
    # completion 4 / 5 (the 11 not-yet-due are out) × 100 × 0.6 = 48, schedule 50 × 0.4 = 20
    assert score == pytest.approx(68.0)
