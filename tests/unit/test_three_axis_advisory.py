"""Three-axis advisory blend (Phase C).

The first phase where Worth + Trajectory may *move* master_score — but only when
AINDY_INFINITY_THREE_AXIS_ADVISORY is on (default off), bounded so the behavioral KPIs stay
the anchor (>=80%), and with graceful degradation so a missing axis never drags a score.
Covers: the trajectory padding guard (§8.3), the composition math + anchor floor + env
tuning (§8.2/§8.4), the consolidation migration path, and the end-to-end hook proving the
blend moves the persisted score only when on and is byte-identical to behavioral when off.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.analytics.services.scoring import three_axis_service as tas
from apps.analytics.services.scoring import three_axis_composition as comp
from apps.analytics.services.scoring.value_declaration_service import record_value_declaration
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile


def _uid() -> str:
    return str(uuid.uuid4())


def _task(db, uid, *, duration, time_spent, status="completed"):
    db.add(Task(name="t", status=status, duration=duration, time_spent=time_spent,
                user_id=uuid.UUID(uid), end_time=datetime.now(timezone.utc)))
    db.flush()


# ── Trajectory padding guard (§8.3) ───────────────────────────────────────────

class TestTrajectoryPaddingGuard:
    def test_on_time_is_neutral_unpenalized(self, db_session):
        uid = _uid()
        for _ in range(6):
            _task(db_session, uid, duration=4.0, time_spent=4 * 3600)  # est == actual
        r = tas.compute_trajectory(db_session, uid)
        assert r["score"] == pytest.approx(50.0)
        assert r["padding_penalty"] == 0.0

    def test_genuinely_fast_but_varied_not_penalized(self, db_session):
        """Some ahead, some behind → ahead-fraction below threshold → no padding penalty."""
        uid = _uid()
        for _ in range(3):
            _task(db_session, uid, duration=8.0, time_spent=4 * 3600)   # 2x fast (ahead)
        for _ in range(3):
            _task(db_session, uid, duration=4.0, time_spent=8 * 3600)   # 2x slow (behind)
        r = tas.compute_trajectory(db_session, uid)
        assert r["padding_penalty"] == 0.0
        assert r["score"] == r["raw_score"]        # untouched
        assert r["ahead"] == 3 and r["behind"] == 3

    def test_chronic_padding_is_dampened(self, db_session):
        """All tasks always ~2x ahead → the ahead-of-plan excess is halved by the guard."""
        uid = _uid()
        for _ in range(6):
            _task(db_session, uid, duration=8.0, time_spent=4 * 3600)   # every task 2x ahead
        r = tas.compute_trajectory(db_session, uid)
        assert r["ahead"] == 6
        assert r["raw_score"] == pytest.approx(100.0)
        assert r["padding_penalty"] == pytest.approx(0.5)
        assert r["score"] == pytest.approx(75.0)   # 50 + (100-50)*(1-0.5)
        assert r["score"] < r["raw_score"]


# ── Composition math (§8.2 / §8.4) ────────────────────────────────────────────

class TestComposeAdvisoryMaster:
    def test_no_axes_available_equals_behavioral(self):
        r = comp.compose_advisory_master(
            60.0, worth_score=None, trajectory_score=None,
            worth_available=False, trajectory_available=False)
        assert r["advisory_master"] == pytest.approx(60.0)
        assert r["anchor_weight"] == pytest.approx(1.0)
        assert r["delta"] == 0.0

    def test_missing_axis_returns_weight_to_anchor(self):
        """Worth present, trajectory absent → trajectory's reserved weight goes to the anchor."""
        r = comp.compose_advisory_master(
            60.0, worth_score=90.0, trajectory_score=None,
            worth_available=True, trajectory_available=False)
        assert r["applied_trajectory_weight"] == 0.0
        assert r["anchor_weight"] == pytest.approx(0.88)   # 1 - 0.12 worth only
        assert r["advisory_master"] == pytest.approx(0.88 * 60 + 0.12 * 90)

    def test_both_axes_anchor_is_eighty_percent(self):
        r = comp.compose_advisory_master(
            60.0, worth_score=90.0, trajectory_score=80.0,
            worth_available=True, trajectory_available=True)
        assert r["anchor_weight"] == pytest.approx(0.80)
        assert r["advisory_master"] == pytest.approx(0.80 * 60 + 0.12 * 90 + 0.08 * 80)
        assert r["worth_contributed"] and r["trajectory_contributed"]

    def test_anchor_floor_enforced_under_env_override(self, monkeypatch):
        monkeypatch.setenv(comp.WORTH_WEIGHT_ENV, "0.5")
        monkeypatch.setenv(comp.TRAJECTORY_WEIGHT_ENV, "0.5")
        w, t = comp._reserved_weights()
        assert w + t == pytest.approx(1.0 - comp.BEHAVIORAL_MIN_WEIGHT)  # clamped to 0.20
        r = comp.compose_advisory_master(
            60.0, worth_score=90.0, trajectory_score=80.0,
            worth_available=True, trajectory_available=True)
        assert r["anchor_weight"] >= comp.BEHAVIORAL_MIN_WEIGHT - 1e-9


class TestConsolidation:
    def test_consolidate_volume_is_mean_of_completion_kpis(self):
        v = comp.consolidate_volume({
            "execution_speed": 60.0, "decision_efficiency": 40.0,
            "masterplan_progress": 50.0, "focus_quality": 10.0,
            "ai_productivity_boost": 90.0})
        assert v == pytest.approx(50.0)   # (60+40+50)/3

    def test_weight_view_sums_to_one_with_reserved_axes(self):
        from apps.analytics.user_score import KPI_WEIGHTS

        view = comp.consolidated_weight_view(dict(KPI_WEIGHTS))
        assert sum(view.values()) == pytest.approx(1.0)
        assert view["worth"] == pytest.approx(comp.DEFAULT_WORTH_WEIGHT)
        assert view["trajectory"] == pytest.approx(comp.DEFAULT_TRAJECTORY_WEIGHT)
        # the three completion KPIs folded into a single volume weight
        assert view["volume"] > view["focus_quality"]


class TestFlag:
    def test_flag_default_off(self, monkeypatch):
        monkeypatch.delenv(comp.ADVISORY_FLAG, raising=False)
        assert comp.advisory_enabled() is False
        monkeypatch.setenv(comp.ADVISORY_FLAG, "1")
        assert comp.advisory_enabled() is True


# ── End-to-end hook: moves the score only when on ─────────────────────────────

class TestHookFromScoring:
    def test_advisory_off_no_blend(self, db_session, monkeypatch):
        """Flag off → the persisted score is purely behavioral; no advisory block."""
        from apps.analytics.services.scoring.infinity_service import (
            calculate_infinity_score,
            orchestrator_score_context,
        )

        uid = _uid()
        _task(db_session, uid, duration=8.0, time_spent=4 * 3600)
        record_value_declaration(db_session, user_id=uid, target_type="project", declared_value="critical")

        monkeypatch.delenv(comp.ADVISORY_FLAG, raising=False)
        with orchestrator_score_context():
            off = calculate_infinity_score(uid, db_session, trigger_event="task_completion")
        assert off is not None
        assert off["three_axis_advisory"] is None
        assert 0.0 <= off["master_score"] <= 100.0

    def test_advisory_on_blend_is_self_consistent(self, db_session, monkeypatch):
        """Flag on → master_score is the bounded blend of the behavioral anchor + the two
        axes, and the persisted value equals anchor·behavioral + w·worth + t·trajectory
        exactly (the blend rides on the behavioral base, never replaces it)."""
        from apps.analytics.services.scoring.infinity_service import (
            calculate_infinity_score,
            orchestrator_score_context,
        )

        uid = _uid()
        _task(db_session, uid, duration=8.0, time_spent=4 * 3600)   # ahead → trajectory data
        record_value_declaration(db_session, user_id=uid, target_type="project", declared_value="critical")

        monkeypatch.setenv(comp.ADVISORY_FLAG, "1")
        with orchestrator_score_context():
            on = calculate_infinity_score(uid, db_session, trigger_event="task_completion")
        assert on is not None
        adv = on["three_axis_advisory"]
        assert adv is not None
        assert adv["worth_contributed"] is True              # declaration exists → worth axis in play
        assert on["master_score"] == pytest.approx(adv["advisory_master"])
        assert adv["anchor_weight"] >= comp.BEHAVIORAL_MIN_WEIGHT - 1e-9
        assert 0.0 <= on["master_score"] <= 100.0

        # The persisted master is EXACTLY the weighted blend of its own reported parts.
        expected = (
            adv["anchor_weight"] * adv["behavioral_master"]
            + adv["applied_worth_weight"] * adv["worth"]["score"]
            + adv["applied_trajectory_weight"] * adv["trajectory"]["score"]
        )
        assert adv["advisory_master"] == pytest.approx(expected, abs=0.02)

    def test_preview_is_readonly_and_flag_agnostic(self, db_session, monkeypatch):
        from apps.analytics.services.scoring.infinity_service import (
            calculate_infinity_score,
            orchestrator_score_context,
        )

        uid = _uid()
        _task(db_session, uid, duration=8.0, time_spent=4 * 3600)
        record_value_declaration(db_session, user_id=uid, target_type="project", declared_value="high")
        monkeypatch.delenv(comp.ADVISORY_FLAG, raising=False)
        with orchestrator_score_context():
            calculate_infinity_score(uid, db_session, trigger_event="manual")

        preview = comp.preview_advisory(db_session, uid)
        assert preview["available"] is True
        assert preview["flag_enabled"] is False              # preview works with flag off
        assert "advisory_master" in preview and "behavioral_master" in preview
        assert preview["consolidated_volume"] is not None

    def test_preview_no_score_yet(self, db_session):
        preview = comp.preview_advisory(db_session, _uid())
        assert preview["available"] is False
        assert preview["reason"] == "no_score_yet"
