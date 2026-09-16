"""Pace is a proposal the human confirms, not a re-sequencing the system performs.

`BUILD_PLAN` "Risk posture & ETA drift → actuation". Posture (the declared appetite) becomes a
drift tolerance; `days_ahead_behind` (the daily ETA job's measurement) is read against it; past
the tolerance, on a confident projection, the system proposes. The human confirms `retarget` (a
refine: target_date moves to the projected completion) or dismisses, and a dismissal stays until
the drift moves by more than the tolerance — the phase-advance semantics, applied to pace.

★ The assertions that matter: proposing writes nothing; low confidence proposes nothing; the
tolerance is the posture's; confirming is refused without a proposal; dismissing is measured.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import pace

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _plan(db, *, posture="Stable", days_ahead_behind=None, confidence="high", remaining_days=365):
    target = (NOW + timedelta(days=remaining_days)).replace(tzinfo=None)
    projected = None
    if days_ahead_behind is not None:
        projected = (target - timedelta(days=days_ahead_behind)).date()
    row = MasterPlan(
        start_date=datetime(2026, 1, 1), duration_years=2.0, target_date=target, user_id=USER,
        status="locked", structure_json={}, posture=posture,
        days_ahead_behind=days_ahead_behind, eta_confidence=confidence,
        projected_completion_date=projected, current_velocity=0.4,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ── tolerance is the posture's ────────────────────────────────────────────────────────

def test_tolerance_scales_with_posture_and_remaining_horizon():
    assert pace.pace_tolerance_days("Aggressive", 365) == 18     # 5 % of 365
    assert pace.pace_tolerance_days("Accelerated", 365) == 36    # 10 % (36.5 rounds to even)
    assert pace.pace_tolerance_days("Stable", 365) == 73         # 20 %
    assert pace.pace_tolerance_days("Reduced", 365) == 128       # 35 %


def test_tolerance_has_a_floor_so_a_plan_in_its_last_month_is_not_nagged_daily():
    assert pace.pace_tolerance_days("Aggressive", 20) == 7
    assert pace.pace_tolerance_days("Stable", 20) == 30
    assert pace.pace_tolerance_days(None, 365) == 73             # unknown posture reads as Stable


# ── proposing ─────────────────────────────────────────────────────────────────────────

def test_drift_within_tolerance_proposes_nothing(db_session):
    plan = _plan(db_session, posture="Stable", days_ahead_behind=-30)   # tolerance 73
    out = pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)
    assert out["proposed"] is False
    assert out["reason"] == "within_tolerance"
    assert out["evidence"]["tolerance_days"] == 73


def test_the_same_drift_proposes_on_an_aggressive_plan(db_session):
    plan = _plan(db_session, posture="Aggressive", days_ahead_behind=-30)   # tolerance 18
    out = pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)
    assert out["proposed"] is True
    assert out["direction"] == "behind"
    assert out["reason"] == "behind_beyond_tolerance"
    decisions = [o["decision"] for o in out["options"]]
    assert "retarget" in decisions
    retarget = next(o for o in out["options"] if o["decision"] == "retarget")
    assert retarget["kind"] == "refine"
    assert retarget["consequence"]["days"] == -30
    # The implied appetite is NAMED, not offered: revise-class, and /revise is not built.
    named = [o for o in out["options"] if o["decision"] is None]
    assert named and named[0]["kind"] == "revise" and "Accelerated" in named[0]["label"]


def test_ahead_of_schedule_proposes_too(db_session):
    plan = _plan(db_session, posture="Stable", days_ahead_behind=120)
    out = pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)
    assert out["proposed"] is True and out["direction"] == "ahead"
    assert out["evidence"]["implied_posture"] == "Accelerated"


def test_low_confidence_proposes_nothing_but_still_shows_the_evidence(db_session):
    plan = _plan(db_session, posture="Aggressive", days_ahead_behind=-90, confidence="low")
    out = pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)
    assert out["proposed"] is False
    assert out["reason"] == "low_confidence"
    assert out["evidence"]["days_ahead_behind"] == -90 and out["evidence"]["exceeds_tolerance"] is True


def test_no_projection_proposes_nothing(db_session):
    plan = _plan(db_session, days_ahead_behind=None, confidence="insufficient_data")
    out = pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)
    assert out["proposed"] is False and out["reason"] == "no_projection"


def test_proposing_writes_nothing(db_session):
    plan = _plan(db_session, posture="Aggressive", days_ahead_behind=-30)
    before = (plan.target_date, plan.pace_dismissed_at, plan.days_ahead_behind)
    pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)
    db_session.refresh(plan)
    assert (plan.target_date, plan.pace_dismissed_at, plan.days_ahead_behind) == before


# ── dismissing ────────────────────────────────────────────────────────────────────────

def test_dismissal_stands_until_drift_moves_past_the_tolerance(db_session):
    plan = _plan(db_session, posture="Aggressive", days_ahead_behind=-30)  # tolerance 18
    out = pace.dismiss_pace_review(db_session, masterplan_id=plan.id, user_id=USER)
    assert out["dismissed"]["days_ahead_behind"] == -30

    again = pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)
    assert again["proposed"] is False and again["dismissed"]["days_ahead_behind"] == -30

    plan.days_ahead_behind = -40   # moved 10: inside the tolerance, still the same question
    db_session.commit()
    assert pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)["proposed"] is False

    plan.days_ahead_behind = -60   # moved 30: a different question
    db_session.commit()
    assert pace.propose_pace_review(db_session, masterplan_id=plan.id, user_id=USER, now=NOW)["proposed"] is True


def test_dismissing_with_nothing_proposed_is_refused(db_session):
    plan = _plan(db_session, posture="Stable", days_ahead_behind=-10)
    with pytest.raises(ValueError, match="nothing to decline"):
        pace.dismiss_pace_review(db_session, masterplan_id=plan.id, user_id=USER)


# ── confirming ────────────────────────────────────────────────────────────────────────

def test_confirm_retarget_moves_the_target_date_to_the_projection_and_clears_the_dismissal(db_session, monkeypatch):
    plan = _plan(db_session, posture="Aggressive", days_ahead_behind=-30)
    old_target = plan.target_date
    projected = plan.projected_completion_date
    # The ETA recompute is a live-data path; here it is enough that it is asked for.
    called = {}
    monkeypatch.setattr(
        "apps.masterplan.services.eta_service.calculate_eta",
        lambda db, mid, uid: called.update(mid=mid) or {"days_ahead_behind": 0, "eta_confidence": "high"},
    )

    out = pace.confirm_pace_review(db_session, masterplan_id=plan.id, user_id=USER, decision="retarget")

    db_session.refresh(plan)
    assert plan.target_date.date() == projected
    assert plan.target_date != old_target
    assert out["kind"] == "refine" and out["target_date_to"].startswith(projected.isoformat())
    assert called["mid"] == plan.id
    assert plan.pace_dismissed_at is None and plan.pace_dismissed_days is None


def test_confirming_with_nothing_proposed_is_refused(db_session):
    plan = _plan(db_session, posture="Stable", days_ahead_behind=-10)
    with pytest.raises(ValueError, match="nothing to confirm"):
        pace.confirm_pace_review(db_session, masterplan_id=plan.id, user_id=USER, decision="retarget")


def test_an_unknown_decision_is_refused(db_session):
    plan = _plan(db_session, posture="Aggressive", days_ahead_behind=-30)
    with pytest.raises(ValueError, match="unknown decision"):
        pace.confirm_pace_review(db_session, masterplan_id=plan.id, user_id=USER, decision="reposture")


def test_confirming_never_re_sequences_tasks(db_session, monkeypatch):
    """The actuation is the proposal. Nothing here touches tasks, phases or strategies."""
    from apps.masterplan.strategy_layer import PlanPhase, PlanStrategy
    from apps.tasks.models import Task

    plan = _plan(db_session, posture="Aggressive", days_ahead_behind=-30)
    monkeypatch.setattr("apps.masterplan.services.eta_service.calculate_eta", lambda *a, **k: {})
    counts = lambda: (db_session.query(Task).count(), db_session.query(PlanPhase).count(), db_session.query(PlanStrategy).count())  # noqa: E731
    before = counts()
    pace.confirm_pace_review(db_session, masterplan_id=plan.id, user_id=USER, decision="retarget")
    assert counts() == before
    assert date.today()  # sanity: nothing above depended on wall-clock
