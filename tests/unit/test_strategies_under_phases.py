"""Strategies are how a phase gets done, and the phase's evidence reads them.

`STRATEGY_LAYER_SPEC` §5, made real on 2026-09-10 after the owner added three ~200-hour
"tasks" to Foundation Building — *Establish Authority*, *Build Intellectual Property*, *Build
a working technical prototype* — and then said: *"each one I just added could be days, weeks
or months long."* Those are strategies wearing task rows: §3's flattening, one tier down.

★ The three assertions that matter:

- a phase's work is its **strategies and its direct tasks**; tasks under a strategy count
  toward the strategy, and the strategy's verdict is what the phase sees
- a task created under a strategy is **scheduled where the strategy is**
- promoting a task to a strategy **deletes the placeholder and keeps the estimate in words**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import phase_advance as pa
from apps.masterplan.services import strategy_layer_service as layer
from apps.masterplan.services.strategy_layer_seed import seed_strategy_layer
from apps.masterplan.strategy_layer import PlanPhase, PlanStrategy
from apps.tasks.models import Task
from apps.tasks.services import task_service
from apps.tasks.services.task_service import create_task

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
START = datetime(2026, 1, 1)
MID = datetime(2026, 9, 10, tzinfo=timezone.utc)
STRUCTURE = {"phases": [
    {"name": "Foundation Building", "duration_months": 12},
    {"name": "Platform Development", "duration_months": 12},
]}


@pytest.fixture(autouse=True)
def _owned(monkeypatch):
    monkeypatch.setattr(task_service, "assert_masterplan_owned_via_syscall", lambda *a, **k: None)


@pytest.fixture
def plan(db_session):
    row = MasterPlan(start_date=START, duration_years=2.0, target_date=datetime(2028, 1, 1),
                     user_id=USER, status="locked", structure_json=STRUCTURE)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    seed_strategy_layer(db_session, masterplan_id=row.id)
    return row


def _phases(db, plan):
    return db.query(PlanPhase).filter(PlanPhase.masterplan_id == plan.id).order_by(PlanPhase.ordinal).all()


def _strategy(db, plan, name, *, phase):
    return layer.create_strategy(db, user_id=USER, masterplan_id=plan.id, name=name, phase_id=phase.id)


def _propose(db, plan):
    return pa.propose_phase_advance(db, masterplan_id=plan.id, user_id=USER, now=MID)


# ── scheduling ────────────────────────────────────────────────────────────────────────

def test_a_task_under_a_strategy_is_scheduled_where_the_strategy_is(db_session, plan):
    first, second = _phases(db_session, plan)
    st = _strategy(db_session, plan, "Establish Authority", phase=second)

    task = create_task(db_session, "Write three essays", masterplan_id=plan.id,
                       user_id=str(USER), strategy_id=st["id"])

    assert (task.strategy_id, task.phase_id) == (st["id"], second.id)


def test_a_strategy_from_another_plan_is_refused(db_session, plan):
    other = MasterPlan(start_date=START, duration_years=2.0, target_date=datetime(2028, 1, 1),
                       user_id=USER, status="locked", structure_json=STRUCTURE)
    db_session.add(other)
    db_session.commit()
    seed_strategy_layer(db_session, masterplan_id=other.id)
    foreign = _strategy(db_session, other, "theirs", phase=_phases(db_session, other)[0])

    with pytest.raises(ValueError, match="strategy_not_on_plan"):
        create_task(db_session, "x", masterplan_id=plan.id, user_id=str(USER), strategy_id=foreign["id"])


# ── ★ the phase reads its strategies ──────────────────────────────────────────────────

def test_an_open_strategy_keeps_the_phase_open_whatever_its_tasks_say(db_session, plan):
    """A strategy's tasks can all be done and the strategy still not concluded — the
    verdict is the human's. The phase sees the verdict, not the tasks."""
    first = _phases(db_session, plan)[0]
    st = _strategy(db_session, plan, "Establish Authority", phase=first)
    create_task(db_session, "Essay", masterplan_id=plan.id, user_id=str(USER), strategy_id=st["id"])
    db_session.query(Task).update({"status": "completed"})
    db_session.commit()

    result = _propose(db_session, plan)

    assert result["proposed"] is False
    assert result["evidence"]["strategies_total"] == 1
    assert result["evidence"]["strategies_finished"] == 0
    assert result["evidence"]["tasks_total"] == 0, "tasks under a strategy are not direct tasks"


def test_every_strategy_finished_and_every_direct_task_done_proposes(db_session, plan):
    first = _phases(db_session, plan)[0]
    worked = _strategy(db_session, plan, "Establish Authority", phase=first)
    dropped = _strategy(db_session, plan, "Build IP", phase=first)
    layer.conclude_strategy(db_session, strategy_id=worked["id"], outcome="worked")
    layer.displace_strategy(db_session, strategy_id=dropped["id"], note="did the prototype instead")
    db_session.add(Task(name="Fix Nodus Issues", user_id=USER, status="completed", priority="medium",
                        masterplan_id=plan.id, duration=1.0, phase_id=first.id))
    db_session.commit()

    result = _propose(db_session, plan)

    assert result["proposed"] is True
    assert result["evidence"]["strategies_finished"] == 2
    assert result["evidence"]["work_units"] == 3


def test_a_dismissal_lapses_when_a_strategy_is_added(db_session, plan):
    """★ The owner's loop: NOT DONE → describe the phase → the question returns."""
    first = _phases(db_session, plan)[0]
    db_session.add(Task(name="Fix Nodus Issues", user_id=USER, status="completed", priority="medium",
                        masterplan_id=plan.id, duration=1.0, phase_id=first.id))
    db_session.commit()
    pa.dismiss_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    assert _propose(db_session, plan)["dismissed"] is not None

    _strategy(db_session, plan, "Establish Authority", phase=first)

    after = _propose(db_session, plan)
    assert after["dismissed"] is None
    assert after["proposed"] is False, "and there is open work now, so nothing to propose"


def test_confirming_carries_an_unfinished_strategy_and_its_tasks_forward(db_session, plan, monkeypatch):
    monkeypatch.setattr(pa, "_now", lambda: datetime(2027, 2, 1, tzinfo=timezone.utc))
    first, second = _phases(db_session, plan)
    st = _strategy(db_session, plan, "Establish Authority", phase=first)
    task = create_task(db_session, "Essay", masterplan_id=plan.id, user_id=str(USER), strategy_id=st["id"])

    result = pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    db_session.expire_all()

    assert result["review"]["moved_strategy_ids"] == [st["id"]]
    assert result["review"]["moved_task_ids"] == [], "the task moved with its strategy, not on its own"
    assert db_session.query(PlanStrategy).get(st["id"]).phase_id == second.id
    assert db_session.query(Task).get(task.id).phase_id == second.id


# ── ★ promotion ───────────────────────────────────────────────────────────────────────

def test_promoting_a_task_makes_a_strategy_on_its_phase_and_removes_the_placeholder(db_session, plan):
    first = _phases(db_session, plan)[0]
    row = Task(name="Establish Authority", user_id=USER, status="in_progress", priority="medium",
               masterplan_id=plan.id, duration=201.75, phase_id=first.id)
    db_session.add(row)
    db_session.commit()

    result = pa.promote_task_to_strategy(db_session, masterplan_id=plan.id, task_id=row.id, user_id=USER)

    st = result["strategy"]
    assert (st["name"], st["phase_id"], st["status"]) == ("Establish Authority", first.id, "active")
    assert "201.75 hours" in st["description"]
    assert result["task_deleted"] is True
    assert db_session.query(Task).get(row.id) is None


def test_a_completed_task_is_not_promoted(db_session, plan):
    """It was work, and work stays a task."""
    first = _phases(db_session, plan)[0]
    row = Task(name="Fix Nodus Issues", user_id=USER, status="completed", priority="medium",
               masterplan_id=plan.id, duration=1.0, phase_id=first.id)
    db_session.add(row)
    db_session.commit()

    with pytest.raises(ValueError, match="work stays a task"):
        pa.promote_task_to_strategy(db_session, masterplan_id=plan.id, task_id=row.id, user_id=USER)
    assert db_session.query(Task).get(row.id) is not None


# ── ★ attribution: worked on THIS ─────────────────────────────────────────────────────

def test_strategy_task_counts_say_worked_on_this(db_session, plan):
    """§5b. The first number in the system that attributes work to an approach."""
    first = _phases(db_session, plan)[0]
    st = _strategy(db_session, plan, "Establish Authority", phase=first)
    done = create_task(db_session, "Essay one", masterplan_id=plan.id, user_id=str(USER),
                       strategy_id=st["id"], duration=6.0)
    create_task(db_session, "Essay two", masterplan_id=plan.id, user_id=str(USER),
                strategy_id=st["id"], duration=10.0)
    done.status = "completed"
    db_session.commit()

    counts = pa.strategy_task_counts(db_session, masterplan_id=plan.id, user_id=USER)

    assert counts == {st["id"]: {"total": 2, "completed": 1, "hours_total": 16.0, "hours_completed": 6.0}}


def test_an_empty_phase_is_not_done_at_either_grain(db_session, plan):
    """Zero strategies and zero tasks is not "all finished"."""
    assert _propose(db_session, plan)["evidence"]["work_complete"] is False
