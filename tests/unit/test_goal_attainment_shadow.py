"""Attainment as a shadow: recorded next to the live score, never applied.

`MASTERPLAN_GOAL_ATTAINMENT_SPEC` §6 Phase 2, built once attribution existed (§4b said WCU
could say THAT you worked, never ON THIS; `STRATEGY_LAYER_SPEC` §5b built the chain).

★ The two assertions that matter: the live `masterplan_progress` is byte-identical with the
shadow on, and a plan whose objectives have no planned work records `attainment_pct = NULL`
with a shadow equal to live — unmeasured is not zero.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.analytics.goal_attainment_shadow import GoalAttainmentShadowRecord
from apps.analytics.services.integration import goal_attainment as ga
from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import phase_advance as pa
from apps.masterplan.services import strategy_layer_service as layer
from apps.masterplan.services.strategy_layer_seed import seed_strategy_layer
from apps.masterplan.strategy_layer import PlanObjective, PlanPhase
from apps.tasks.services import task_service
from apps.tasks.services.task_service import create_task

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
STRUCTURE = {
    "core_domains": [
        {"name": "Ethical AI Framework", "intent": "guidelines"},
        {"name": "Platform Enablement", "intent": "platforms"},
    ],
    "phases": [{"name": "Foundation Building", "duration_months": 12}],
}


@pytest.fixture(autouse=True)
def _owned(monkeypatch):
    monkeypatch.setattr(task_service, "assert_masterplan_owned_via_syscall", lambda *a, **k: None)


@pytest.fixture
def plan(db_session):
    row = MasterPlan(start_date=datetime(2026, 1, 1), duration_years=1.0, target_date=datetime(2027, 1, 1),
                     user_id=USER, status="active", is_active=True, structure_json=STRUCTURE)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    seed_strategy_layer(db_session, masterplan_id=row.id)
    return row


def _objectives(db, plan):
    return db.query(PlanObjective).filter(PlanObjective.masterplan_id == plan.id).order_by(PlanObjective.ordinal).all()


def _phase(db, plan):
    return db.query(PlanPhase).filter(PlanPhase.masterplan_id == plan.id).first()


def _house(db, plan, name, objective, *, hours_done, hours_open):
    st = layer.create_strategy(db, user_id=USER, masterplan_id=plan.id, name=name, phase_id=_phase(db, plan).id)
    layer.set_strategy_objective(db, strategy_id=st["id"], objective_id=objective.id)
    for h in hours_done:
        t = create_task(db, f"{name} done {h}", masterplan_id=plan.id, user_id=str(USER), strategy_id=st["id"], duration=h)
        t.status = "completed"
    for h in hours_open:
        create_task(db, f"{name} open {h}", masterplan_id=plan.id, user_id=str(USER), strategy_id=st["id"], duration=h)
    db.commit()
    return st


# ── masterplan: the answer ────────────────────────────────────────────────────────────

def test_objective_attainment_is_hours_done_against_hours_planned(db_session, plan):
    ethics, platform = _objectives(db_session, plan)
    _house(db_session, plan, "Framework", ethics, hours_done=[6.0], hours_open=[10.0])

    result = pa.objective_attainment(db_session, masterplan_id=plan.id, user_id=USER)

    by = {o["name"]: o for o in result["objectives"]}
    assert by["Ethical AI Framework"]["attainment_pct"] == pytest.approx(6 / 16)
    assert by["Platform Enablement"]["attainment_pct"] is None, "no planned work is unmeasured, not zero"
    assert result["plan"] == {"hours_total": 16.0, "hours_completed": 6.0,
                              "attainment_pct": pytest.approx(6 / 16), "objectives_measured": 1}


def test_plan_attainment_is_hours_weighted_over_housed_work_only(db_session, plan):
    ethics, platform = _objectives(db_session, plan)
    _house(db_session, plan, "Framework", ethics, hours_done=[10.0], hours_open=[])       # 100% of 10
    _house(db_session, plan, "Platform", platform, hours_done=[0.0], hours_open=[30.0])   # 0% of 30
    loose = layer.create_strategy(db_session, user_id=USER, masterplan_id=plan.id, name="Unhoused", phase_id=_phase(db_session, plan).id)
    create_task(db_session, "stray", masterplan_id=plan.id, user_id=str(USER), strategy_id=loose["id"], duration=100.0)

    result = pa.objective_attainment(db_session, masterplan_id=plan.id, user_id=USER)

    assert result["plan"]["attainment_pct"] == pytest.approx(10 / 40), "hours-weighted, not a mean of percentages"
    assert result["unhoused"]["hours_total"] == 100.0, "reported beside, never folded in"


# ── analytics: the blend and the shadow ───────────────────────────────────────────────

def test_the_blend_collapses_to_the_live_formula_when_unmeasured():
    assert ga.blend_with_attainment(completion_pct=0.5, schedule_score=50.0, attainment_pct=None) == 50.0
    assert ga.blend_with_attainment(completion_pct=0.5, schedule_score=50.0, attainment_pct=1.0) == pytest.approx(70.0)
    assert ga.blend_with_attainment(completion_pct=0.5, schedule_score=50.0, attainment_pct=2.0) == pytest.approx(70.0), "clamped"


def test_the_shadow_records_next_to_live_and_changes_nothing(db_session, plan, monkeypatch):
    """★ The whole point."""
    monkeypatch.setenv(ga.SHADOW_FLAG, "1")
    monkeypatch.delenv(ga.LIVE_FLAG, raising=False)
    ethics, _ = _objectives(db_session, plan)
    _house(db_session, plan, "Framework", ethics, hours_done=[8.0], hours_open=[8.0])

    logged = ga.shadow_log_attainment(
        db_session, user_id=USER, live_score=42.0, completion_pct=0.5, schedule_score=50.0,
        masterplan_id=plan.id, trigger_event="test",
    )
    row = db_session.query(GoalAttainmentShadowRecord).one()

    assert logged["live_score"] == 42.0
    assert row.live_score == 42.0, "live is recorded as given, never recomputed or replaced"
    assert row.attainment_pct == pytest.approx(0.5)
    assert row.shadow_score == pytest.approx(0.5 * 100 * 0.40 + 0.5 * 100 * 0.35 + 50 * 0.25)
    assert row.objectives_measured == 1
    assert row.objectives[0]["name"] == "Ethical AI Framework"


def test_an_unmeasured_plan_records_null_attainment_and_shadow_equals_live(db_session, plan, monkeypatch):
    monkeypatch.setenv(ga.SHADOW_FLAG, "1")
    ga.shadow_log_attainment(db_session, user_id=USER, live_score=50.0, completion_pct=0.5,
                             schedule_score=50.0, masterplan_id=plan.id)
    row = db_session.query(GoalAttainmentShadowRecord).one()

    assert row.attainment_pct is None
    assert row.shadow_score == row.live_score == 50.0


def test_the_shadow_flag_off_records_nothing(db_session, plan, monkeypatch):
    monkeypatch.setenv(ga.SHADOW_FLAG, "0")
    assert ga.shadow_log_attainment(db_session, user_id=USER, live_score=50.0, completion_pct=0.5,
                                    schedule_score=50.0, masterplan_id=plan.id) is None
    assert db_session.query(GoalAttainmentShadowRecord).count() == 0


def test_the_shadow_is_on_by_default_and_live_is_off_by_default(monkeypatch):
    monkeypatch.delenv(ga.SHADOW_FLAG, raising=False)
    monkeypatch.delenv(ga.LIVE_FLAG, raising=False)
    assert ga.shadow_enabled() is True, "a shadow nobody records cannot end a soak"
    assert ga.live_enabled() is False, "the flip is a decision, not a default"


def test_the_report_carries_the_divergence_signal(db_session, plan, monkeypatch):
    monkeypatch.setenv(ga.SHADOW_FLAG, "1")
    ethics, _ = _objectives(db_session, plan)
    _house(db_session, plan, "Framework", ethics, hours_done=[16.0], hours_open=[])
    ga.shadow_log_attainment(db_session, user_id=USER, live_score=50.0, completion_pct=0.5,
                             schedule_score=50.0, masterplan_id=plan.id)

    report = ga.attainment_shadow_report(db_session, user_id=USER)

    assert report["count"] == 1 and report["measured"] == 1
    assert report["mean_divergence"] == pytest.approx(70.0 - 50.0)
    assert report["live_enabled"] is False


# ── the live path is untouched unless flipped ─────────────────────────────────────────

def test_masterplan_progress_is_unchanged_with_the_shadow_on(db_session, plan, monkeypatch):
    from apps.analytics.services.scoring import infinity_service as inf

    monkeypatch.setenv(ga.SHADOW_FLAG, "1")
    monkeypatch.delenv(ga.LIVE_FLAG, raising=False)
    monkeypatch.setattr(inf, "_get_user_tasks_for_scoring", lambda uid, db: [{"status": "completed"}, {"status": "pending"}])
    ethics, _ = _objectives(db_session, plan)
    _house(db_session, plan, "Framework", ethics, hours_done=[16.0], hours_open=[])

    # The UUID object, not its str: the plan lookup compares the UUID column directly, which
    # Postgres casts and SQLite does not.
    score, total = inf.calculate_masterplan_progress(USER, db_session)

    assert score == pytest.approx(0.5 * 100 * 0.6 + 50.0 * 0.4)
    assert inf._LAST_PROGRESS_COMPONENTS[str(USER)]["live_score"] == score


def test_masterplan_progress_blends_only_when_flipped(db_session, plan, monkeypatch):
    from apps.analytics.services.scoring import infinity_service as inf

    monkeypatch.setenv(ga.LIVE_FLAG, "1")
    monkeypatch.setattr(inf, "_get_user_tasks_for_scoring", lambda uid, db: [{"status": "completed"}, {"status": "pending"}])
    ethics, _ = _objectives(db_session, plan)
    _house(db_session, plan, "Framework", ethics, hours_done=[16.0], hours_open=[])

    score, _ = inf.calculate_masterplan_progress(USER, db_session)

    assert score == pytest.approx(1.0 * 100 * 0.40 + 0.5 * 100 * 0.35 + 50.0 * 0.25)
