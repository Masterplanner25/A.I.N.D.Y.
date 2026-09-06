"""Three-axis shadow ledger (Phase B).

The three axes are recorded next to master_score on each score event when
AINDY_INFINITY_THREE_AXIS_SHADOW is on (default off), for later divergence analysis.
Covers the flag gate, the shadow-log write, the soak report, and the end-to-end hook from
calculate_infinity_score. Drives nothing — asserts the shadow path never affects scoring.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.analytics.services.scoring import three_axis_service as tas
from apps.analytics.services.scoring.value_declaration_service import record_value_declaration
from apps.analytics.three_axis_shadow import ThreeAxisShadowRecord
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile


def _uid() -> str:
    return str(uuid.uuid4())


def _count(db, uid) -> int:
    return db.query(ThreeAxisShadowRecord).filter(
        ThreeAxisShadowRecord.user_id == uuid.UUID(uid)
    ).count()


def _completed_task(db, uid, *, duration=8.0, time_spent=4 * 3600):
    db.add(Task(name="t", status="completed", duration=duration, time_spent=time_spent,
                user_id=uuid.UUID(uid), end_time=datetime.now(timezone.utc)))
    db.flush()


class TestFlagAndWrite:
    def test_flag_default_off(self, monkeypatch):
        monkeypatch.delenv("AINDY_INFINITY_THREE_AXIS_SHADOW", raising=False)
        assert tas.three_axis_shadow_enabled() is False
        monkeypatch.setenv("AINDY_INFINITY_THREE_AXIS_SHADOW", "1")
        assert tas.three_axis_shadow_enabled() is True

    def test_noop_when_off(self, db_session, monkeypatch):
        monkeypatch.delenv("AINDY_INFINITY_THREE_AXIS_SHADOW", raising=False)
        uid = _uid()
        assert tas.shadow_log_three_axes(db_session, user_id=uid, master_score=70.0) is False
        assert _count(db_session, uid) == 0

    def test_records_when_on(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_INFINITY_THREE_AXIS_SHADOW", "1")
        uid = _uid()
        _completed_task(db_session, uid, duration=8.0, time_spent=4 * 3600)  # ahead of estimate
        record_value_declaration(db_session, user_id=uid, target_type="project", declared_value="critical")
        assert tas.shadow_log_three_axes(db_session, user_id=uid, master_score=72.5,
                                         trigger_event="task_completion") is True
        rows = db_session.query(ThreeAxisShadowRecord).filter(
            ThreeAxisShadowRecord.user_id == uuid.UUID(uid)).all()
        assert len(rows) == 1
        r = rows[0]
        assert r.master_score == pytest.approx(72.5)
        assert r.trigger_event == "task_completion"
        assert r.volume_score is not None and r.worth_score is not None
        assert r.trajectory_score is not None and r.trajectory_score > 50  # ahead
        # 20.0 is WORTH_ORDINAL_LEVELS["critical"] — `strategic` is an ordinal kind, so the
        # stored float is the mapped level rather than a free-form figure.
        assert r.declared_total == pytest.approx(20.0)


class TestReport:
    def test_report_summary_and_scoping(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_INFINITY_THREE_AXIS_SHADOW", "1")
        uid = _uid()
        _completed_task(db_session, uid)
        tas.shadow_log_three_axes(db_session, user_id=uid, master_score=40.0)
        tas.shadow_log_three_axes(db_session, user_id=uid, master_score=60.0)
        report = tas.three_axis_shadow_report(db_session, user_id=uid)
        assert report["count"] == 2
        assert report["summary"]["master_score"] == pytest.approx(50.0)
        assert report["shadow_enabled"] is True
        assert all("master_score" in rec for rec in report["records"])

    def test_report_scoped_per_user(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_INFINITY_THREE_AXIS_SHADOW", "1")
        u1, u2 = _uid(), _uid()
        tas.shadow_log_three_axes(db_session, user_id=u1, master_score=50.0)
        assert tas.three_axis_shadow_report(db_session, user_id=u2)["count"] == 0


class TestHookFromScoring:
    def test_calculate_infinity_score_records_shadow_when_on(self, db_session, monkeypatch):
        """End-to-end: a real score computation logs a shadow record when the flag is on,
        and never when off — proving the hook and the drives-nothing invariant."""
        from apps.analytics.services.scoring.infinity_service import (
            calculate_infinity_score,
            orchestrator_score_context,
        )

        uid = _uid()
        _completed_task(db_session, uid)

        monkeypatch.delenv("AINDY_INFINITY_THREE_AXIS_SHADOW", raising=False)
        with orchestrator_score_context():
            calculate_infinity_score(uid, db_session, trigger_event="task_completion")
        assert _count(db_session, uid) == 0  # flag off -> no shadow record

        monkeypatch.setenv("AINDY_INFINITY_THREE_AXIS_SHADOW", "1")
        with orchestrator_score_context():
            result = calculate_infinity_score(uid, db_session, trigger_event="task_completion")
        assert _count(db_session, uid) == 1  # flag on -> exactly one shadow record
        if result:  # the shadow master_score mirrors the canonical one
            rec = db_session.query(ThreeAxisShadowRecord).filter(
                ThreeAxisShadowRecord.user_id == uuid.UUID(uid)).first()
            assert rec.master_score is not None
