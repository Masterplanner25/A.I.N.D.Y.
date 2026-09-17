"""A strategy whose work is done is proposed for a verdict, not concluded for you.

`STRATEGY_LAYER_SPEC` §8 step 3b(v), built 2026-09-16 as the third instance of the proposal
shape. ★ The assertions that matter, in the order the siblings learned them: proposing writes
nothing; a strategy with no tasks is never proposed; dismissing is refused without a proposal;
a dismissal stands on the evidence it was built on and lapses when the attached work changes;
and confirming is the EXISTING verdict — this module never concludes a strategy itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import strategy_conclude as sc
from apps.masterplan.services import strategy_layer_service as layer
from apps.masterplan.services.strategy_layer_seed import seed_strategy_layer
from apps.masterplan.strategy_layer import STRATEGY_ACTIVE, STRATEGY_CONCLUDED, PlanStrategy
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
STRUCTURE = {"phases": [{"name": "Foundation Building", "duration_months": 12}]}


@pytest.fixture
def plan(db_session):
    row = MasterPlan(
        start_date=datetime(2026, 1, 1), duration_years=1.0, target_date=datetime(2027, 1, 1),
        user_id=USER, status="locked", structure_json=STRUCTURE,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    seed_strategy_layer(db_session, masterplan_id=row.id)
    return row


def _strategy(db, plan, name="Establish Authority", *, start=True):
    created = layer.create_strategy(db, user_id=USER, masterplan_id=plan.id, name=name)
    if start:
        layer.start_strategy(db, strategy_id=created["id"])
    return db.query(PlanStrategy).filter(PlanStrategy.id == created["id"]).one()


def _task(db, plan, strategy, name, *, status="pending", hours=1.0):
    row = Task(name=name, user_id=USER, status=status, priority="medium",
               masterplan_id=plan.id, duration=hours, strategy_id=strategy.id)
    db.add(row)
    db.commit()
    return row


def _proposed_ids(db, plan):
    out = sc.propose_strategy_conclusions(db, masterplan_id=plan.id, user_id=USER)
    return [e["strategy"]["id"] for e in out["proposed"]], out


# ── the evidence ──────────────────────────────────────────────────────────────────────


def test_a_strategy_with_no_tasks_is_never_proposed(db_session, plan):
    _strategy(db_session, plan)
    ids, out = _proposed_ids(db_session, plan)
    assert ids == [] and out["dismissed"] == []


def test_open_work_proposes_nothing(db_session, plan):
    st = _strategy(db_session, plan)
    _task(db_session, plan, st, "write the piece", status="completed")
    _task(db_session, plan, st, "publish it", status="pending")
    ids, _ = _proposed_ids(db_session, plan)
    assert ids == []


def test_all_work_done_proposes_with_the_numbers(db_session, plan):
    st = _strategy(db_session, plan)
    _task(db_session, plan, st, "write the piece", status="completed", hours=2.0)
    _task(db_session, plan, st, "publish it", status="completed", hours=1.0)
    ids, out = _proposed_ids(db_session, plan)
    assert ids == [st.id]
    (entry,) = out["proposed"]
    assert entry["reason"] == "work_complete"
    assert entry["evidence"] == {
        "tasks_total": 2, "tasks_completed": 2,
        "hours_total": 3.0, "hours_completed": 3.0, "work_complete": True,
    }


def test_only_active_strategies_are_proposed(db_session, plan):
    proposed_only = _strategy(db_session, plan, "Not started yet", start=False)
    _task(db_session, plan, proposed_only, "done anyway", status="completed")
    ids, _ = _proposed_ids(db_session, plan)
    assert ids == []


def test_proposing_writes_nothing(db_session, plan):
    st = _strategy(db_session, plan)
    _task(db_session, plan, st, "write the piece", status="completed")
    before = (st.status, st.outcome, st.concluded_at, st.conclude_dismissed_at)
    _proposed_ids(db_session, plan)
    db_session.refresh(st)
    assert (st.status, st.outcome, st.concluded_at, st.conclude_dismissed_at) == before
    assert st.status == STRATEGY_ACTIVE


# ── decline ───────────────────────────────────────────────────────────────────────────


def test_dismissing_without_a_proposal_is_refused(db_session, plan):
    st = _strategy(db_session, plan)
    _task(db_session, plan, st, "still open", status="pending")
    with pytest.raises(ValueError, match="nothing to decline"):
        sc.dismiss_strategy_conclusion(db_session, masterplan_id=plan.id, strategy_id=st.id, user_id=USER)


def test_a_dismissal_stands_until_the_attached_work_changes(db_session, plan):
    st = _strategy(db_session, plan)
    _task(db_session, plan, st, "write the piece", status="completed")
    out = sc.dismiss_strategy_conclusion(db_session, masterplan_id=plan.id, strategy_id=st.id, user_id=USER)
    assert out["dismissed"]["task_count"] == 1
    assert out["returns_when"] == "the strategy's attached tasks change"

    ids, listing = _proposed_ids(db_session, plan)
    assert ids == [], "the human said not done on this exact evidence"
    assert [e["strategy"]["id"] for e in listing["dismissed"]] == [st.id]

    # Attaching the task that was missing is new evidence — the question is asked again once
    # that task is done too.
    _task(db_session, plan, st, "the missing one", status="completed")
    ids, listing = _proposed_ids(db_session, plan)
    assert ids == [st.id] and listing["dismissed"] == []


def test_a_strategy_on_another_plan_cannot_be_dismissed_through_this_one(db_session, plan):
    other = MasterPlan(
        start_date=datetime(2026, 1, 1), duration_years=1.0, target_date=datetime(2027, 1, 1),
        user_id=USER, status="locked", structure_json=STRUCTURE,
    )
    db_session.add(other)
    db_session.commit()
    st = _strategy(db_session, other)
    _task(db_session, other, st, "done", status="completed")
    with pytest.raises(ValueError, match="not on plan"):
        sc.dismiss_strategy_conclusion(db_session, masterplan_id=plan.id, strategy_id=st.id, user_id=USER)


# ── confirm is the existing verdict ───────────────────────────────────────────────────


def test_the_verdict_route_is_the_confirmation_and_ends_the_proposal(db_session, plan):
    st = _strategy(db_session, plan)
    _task(db_session, plan, st, "write the piece", status="completed")
    assert _proposed_ids(db_session, plan)[0] == [st.id]

    layer.conclude_strategy(db_session, strategy_id=st.id, outcome="worked", note="it did")
    db_session.refresh(st)
    assert st.status == STRATEGY_CONCLUDED
    assert _proposed_ids(db_session, plan)[0] == []
