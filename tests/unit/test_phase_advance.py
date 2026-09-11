"""Phase advance is a proposal the human confirms, not a status the system flips.

`STRATEGY_LAYER_SPEC` §6 Q8 / §8 step 3b. The owner, 2026-09-05: *"A phase being completed
should trigger something like a review/refine of the plan — especially if you finish some
things quicker than you thought. Maybe some things move phases."*

★ **The two assertions that matter:** proposing writes nothing, and confirming is refused
without a proposal to agree with. Everything else is the evidence being read correctly — off
the plan's own phases and the work attached to them, not off `evaluate_phase`'s threshold
columns (books, a studio, playbooks) that no plan ever declared.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import phase_advance as pa
from apps.masterplan.services import wcu_service
from apps.masterplan.services.strategy_layer_seed import seed_strategy_layer
from apps.masterplan.strategy_layer import PHASE_ACTIVE, PHASE_COMPLETE, PHASE_PENDING, PlanPhase
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
START = datetime(2026, 1, 1)

STRUCTURE = {
    "phases": [
        {"name": "Foundation Building", "duration_months": 12},
        {"name": "Platform Development", "duration_months": 12},
        {"name": "Expansion and Scaling", "duration_months": 12},
    ]
}


@pytest.fixture
def plan(db_session):
    row = MasterPlan(
        start_date=START, duration_years=3.0, target_date=datetime(2029, 1, 1),
        user_id=USER, status="locked", structure_json=STRUCTURE,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    seed_strategy_layer(db_session, masterplan_id=row.id)
    return row


def _phases(db, plan):
    return db.query(PlanPhase).filter(PlanPhase.masterplan_id == plan.id).order_by(PlanPhase.ordinal).all()


def _task(db, plan, name, *, phase, status="pending"):
    row = Task(name=name, user_id=USER, status=status, priority="medium",
               masterplan_id=plan.id, duration=1.0, phase_id=phase.id)
    db.add(row)
    db.commit()
    return row


MID_PHASE_ONE = datetime(2026, 9, 10, tzinfo=timezone.utc)   # 113 days before phase 1 ends
AFTER_PHASE_ONE = datetime(2027, 2, 1, tzinfo=timezone.utc)


# ── the evidence ──────────────────────────────────────────────────────────────────────

def test_nothing_is_proposed_while_work_remains_and_the_window_is_open(db_session, plan):
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Write the framework", phase=first, status="completed")
    _task(db_session, plan, "Publish it", phase=first)

    result = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)

    assert result["proposed"] is False
    assert result["evidence"]["tasks_completed"] == 1
    assert result["evidence"]["tasks_total"] == 2


def test_all_work_done_early_proposes_and_says_by_how_much(db_session, plan):
    """★ The owner's own trigger. *"Especially if you finish some things quicker than you
    thought"* — and the number the review opens with is how much quicker."""
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Write the framework", phase=first, status="completed")
    _task(db_session, plan, "Publish it", phase=first, status="completed")

    result = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)

    assert result["proposed"] is True
    assert result["reason"] == pa.REASON_WORK_COMPLETE
    assert result["phase"]["name"] == "Foundation Building"
    assert result["next_phase"]["name"] == "Platform Development"
    assert result["evidence"]["early_by_days"] == 113


def test_an_elapsed_window_proposes_even_with_work_open(db_session, plan):
    """The calendar ran out. Weaker evidence, but a phase that overran is the other thing a
    review is for — and the open work is named so the review can start with it."""
    first = _phases(db_session, plan)[0]
    done = _task(db_session, plan, "Write the framework", phase=first, status="completed")
    open_task = _task(db_session, plan, "Publish it", phase=first)

    result = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=AFTER_PHASE_ONE)

    assert result["proposed"] is True
    assert result["reason"] == pa.REASON_WINDOW_ELAPSED
    assert result["evidence"]["open_task_ids"] == [open_task.id]
    assert result["evidence"]["early_by_days"] is None
    assert done.id not in result["evidence"]["open_task_ids"]


def test_a_phase_with_no_work_attached_is_not_complete(db_session, plan):
    """Zero of zero is not "all done". An empty phase inside its window proposes nothing."""
    result = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)

    assert result["proposed"] is False
    assert result["evidence"]["work_complete"] is False


def test_proposing_writes_nothing(db_session, plan):
    """★ The system proposes. It does not act."""
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Write the framework", phase=first, status="completed")

    pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)
    db_session.expire_all()

    assert [row.status for row in _phases(db_session, plan)] == [PHASE_PENDING] * 3
    assert db_session.query(MasterPlan).get(plan.id).phase == 1


def test_the_window_is_read_off_the_earlier_phases(db_session, plan):
    phases = _phases(db_session, plan)
    start, end = pa.phase_window(plan, phases, phases[2])

    assert start.date() == (START + timedelta(days=24 * pa._DAYS_PER_MONTH)).date()
    assert (end - start).days == int(12 * pa._DAYS_PER_MONTH)


def test_a_phase_without_a_duration_has_no_window(db_session, plan):
    phases = _phases(db_session, plan)
    phases[1].duration_months = None
    db_session.commit()
    first = phases[0]
    _task(db_session, plan, "x", phase=first)

    assert pa.phase_window(plan, phases, phases[1]) == (
        pa._as_aware(START) + timedelta(days=12 * pa._DAYS_PER_MONTH), None
    )
    assert pa.phase_window(plan, phases, phases[2]) == (None, None)


# ── the frontier ──────────────────────────────────────────────────────────────────────

def test_the_frontier_walks_the_edge(db_session, plan):
    phases = _phases(db_session, plan)
    assert pa.frontier_phase(phases) is phases[0]

    phases[0].status = PHASE_COMPLETE
    db_session.commit()
    assert pa.frontier_phase(phases) is phases[1]

    phases[2].status = PHASE_ACTIVE
    db_session.commit()
    assert pa.frontier_phase(phases) is phases[2], "an active phase is the frontier whatever the chain says"


def test_all_complete_proposes_nothing(db_session, plan):
    for row in _phases(db_session, plan):
        row.status = PHASE_COMPLETE
    db_session.commit()

    result = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER)

    assert result == {"proposed": False, "reason": "all_phases_complete"}


def test_an_unseeded_plan_proposes_nothing(db_session):
    row = MasterPlan(start_date=START, duration_years=1.0, target_date=datetime(2027, 1, 1),
                     user_id=USER, status="locked", structure_json={})
    db_session.add(row)
    db_session.commit()

    assert pa.propose_phase_advance(db_session, masterplan_id=row.id, user_id=USER) == {
        "proposed": False, "reason": "no_phases",
    }


# ── ★ confirming ──────────────────────────────────────────────────────────────────────

def test_confirming_closes_the_phase_opens_the_next_and_moves_the_legacy_integer(
    db_session, plan, monkeypatch
):
    monkeypatch.setattr(pa, "_now", lambda: MID_PHASE_ONE)
    first, second, _ = _phases(db_session, plan)
    _task(db_session, plan, "Write the framework", phase=first, status="completed")

    result = pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    db_session.expire_all()
    first, second, third = _phases(db_session, plan)

    assert (first.status, second.status, third.status) == (PHASE_COMPLETE, PHASE_ACTIVE, PHASE_PENDING)
    assert first.completed_at is not None and second.started_at is not None
    assert result["completed"]["id"] == first.id
    assert result["activated"]["id"] == second.id
    assert result["plan_phase"] == 2
    assert db_session.query(MasterPlan).get(plan.id).phase == 2
    assert result["review"] == {
        "reason": pa.REASON_WORK_COMPLETE, "early_by_days": 113,
        "moved_task_ids": [], "moved_to_phase_id": None,
    }


def test_confirming_carries_open_work_into_the_next_phase(db_session, plan, monkeypatch):
    """★ *"Maybe some things move phases."* A closed phase cannot hold open work; the next
    phase is the only defensible destination; and the moved ids are what the review opens
    with — they are the things that did not happen when the plan said they would."""
    monkeypatch.setattr(pa, "_now", lambda: AFTER_PHASE_ONE)
    first, second, _ = _phases(db_session, plan)
    done = _task(db_session, plan, "Write the framework", phase=first, status="completed")
    late = _task(db_session, plan, "Publish it", phase=first)

    result = pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    db_session.expire_all()

    assert result["review"]["moved_task_ids"] == [late.id]
    assert result["review"]["moved_to_phase_id"] == second.id
    assert db_session.query(Task).get(late.id).phase_id == second.id
    assert db_session.query(Task).get(done.id).phase_id == first.id, "completed work stays where it was done"


def test_confirming_without_a_proposal_is_refused(db_session, plan):
    """★ Confirming is agreeing with a proposal. There has to be one."""
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Publish it", phase=first)

    with pytest.raises(ValueError, match="nothing proposes closing"):
        pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    db_session.expire_all()
    assert _phases(db_session, plan)[0].status == PHASE_PENDING


def test_confirming_a_phase_that_is_not_current_is_refused(db_session, plan):
    """The chain is the plan's sequential floor. Closing out of order punches a hole in it."""
    first, second, _ = _phases(db_session, plan)
    _task(db_session, plan, "x", phase=second, status="completed")

    with pytest.raises(ValueError, match="not the plan's current phase"):
        pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=second.id, user_id=USER)


def test_confirming_the_last_phase_leaves_the_plan_complete(db_session, plan, monkeypatch):
    monkeypatch.setattr(pa, "_now", lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))
    phases = _phases(db_session, plan)
    for row in phases[:2]:
        row.status = PHASE_COMPLETE
    db_session.commit()
    _task(db_session, plan, "x", phase=phases[2], status="completed")

    result = pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=phases[2].id, user_id=USER)

    assert result["activated"] is None
    assert result["plan_phase"] == 3
    assert pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER)["reason"] == "all_phases_complete"


# ── ★ what stops flipping ─────────────────────────────────────────────────────────────

def test_wcu_recalculation_no_longer_flips_a_layered_plans_phase(db_session, plan, monkeypatch):
    """★ `calculate_wcu` used to write `evaluate_phase(plan)` onto `plan.phase` on every run.
    For a plan with a layer the phase is whatever `plan_phases` says, and it moves only on
    confirmation. Every threshold satisfied here — the old gate would have said 2."""
    plan.wcu_target = 0
    plan.revenue_target = 0
    plan.books_required = 0
    plan.platform_required = False
    plan.studio_required = False
    plan.playbooks_required = 0
    db_session.commit()
    monkeypatch.setattr(wcu_service, "_graph_context", lambda db, uid: {"nodes": {}})

    result = wcu_service.calculate_wcu(db_session, plan.id, str(USER))

    assert result["phase"] == 1
    assert result["phase_advanced"] is False


def test_wcu_recalculation_reads_the_phase_the_human_confirmed(db_session, plan, monkeypatch):
    monkeypatch.setattr(wcu_service, "_graph_context", lambda db, uid: {"nodes": {}})
    first = _phases(db_session, plan)[0]
    first.status = PHASE_COMPLETE
    db_session.commit()

    result = wcu_service.calculate_wcu(db_session, plan.id, str(USER))

    assert result["phase"] == 2


def test_the_legacy_integer_is_derived_from_the_layer(db_session, plan):
    phases = _phases(db_session, plan)
    assert pa.derive_legacy_phase(phases) == 1
    phases[0].status = PHASE_COMPLETE
    assert pa.derive_legacy_phase(phases) == 2
    for row in phases:
        row.status = PHASE_COMPLETE
    assert pa.derive_legacy_phase(phases) == 3
    assert pa.derive_legacy_phase([]) == 1


# ── ★ declining: "what if the phase isn't complete?" ──────────────────────────────────

def test_dismissing_records_the_evidence_and_silences_the_proposal(db_session, plan):
    """★ The first live proposal drew exactly this question. A proposal that can only be
    accepted is not a proposal."""
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Write the framework", phase=first, status="completed")
    assert pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)["proposed"]

    result = pa.dismiss_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    after = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)

    assert result["dismissed"]["task_count"] == 1
    assert after["proposed"] is False
    assert after["reason"] == pa.REASON_WORK_COMPLETE, "the evidence is still reported"
    assert after["dismissed"]["task_count"] == 1


def test_the_proposal_returns_when_the_phases_work_changes(db_session, plan):
    """★ Not on a timer — on the only thing that could change the answer. Attaching the task
    that was missing is the review, arrived at from the other direction."""
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Write the framework", phase=first, status="completed")
    pa.dismiss_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)

    _task(db_session, plan, "Publish it", phase=first)
    with_open_work = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)
    assert with_open_work["proposed"] is False
    assert with_open_work["dismissed"] is None, "the dismissal lapsed; there is simply no proposal"

    db_session.query(Task).filter(Task.name == "Publish it").update({"status": "completed"})
    db_session.commit()
    done_again = pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)
    assert done_again["proposed"] is True, "two tasks is a different question from one"


def test_dismissing_without_a_proposal_is_refused(db_session, plan):
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Publish it", phase=first)

    with pytest.raises(ValueError, match="nothing to decline"):
        pa.dismiss_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)


def test_a_dismissed_proposal_cannot_be_confirmed_by_accident_but_can_on_purpose(db_session, plan, monkeypatch):
    """Dismissal silences the proposal; it does not lock the phase. The human may change
    their mind, and confirming is an explicit act against the same evidence."""
    monkeypatch.setattr(pa, "_now", lambda: MID_PHASE_ONE)
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Write the framework", phase=first, status="completed")
    pa.dismiss_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)

    result = pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)

    assert result["completed"]["status"] == PHASE_COMPLETE


# ── ★ reopening: the confirmation was a mistake ───────────────────────────────────────

def _confirm_first(db, plan, monkeypatch):
    monkeypatch.setattr(pa, "_now", lambda: MID_PHASE_ONE)
    first = _phases(db, plan)[0]
    _task(db, plan, "Write the framework", phase=first, status="completed")
    return pa.confirm_phase_advance(db, masterplan_id=plan.id, phase_id=first.id, user_id=USER)


def test_reopening_reverses_the_confirmation(db_session, plan, monkeypatch):
    _confirm_first(db_session, plan, monkeypatch)
    first, second, _ = _phases(db_session, plan)
    assert (first.status, second.status) == (PHASE_COMPLETE, PHASE_ACTIVE)

    result = pa.reopen_phase(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    db_session.expire_all()
    first, second, _ = _phases(db_session, plan)

    assert (first.status, second.status) == (PHASE_ACTIVE, PHASE_PENDING)
    assert first.completed_at is None and second.started_at is None
    assert result["plan_phase"] == 1
    assert db_session.query(MasterPlan).get(plan.id).phase == 1
    assert pa.frontier_phase(_phases(db_session, plan)) is first


def test_reopening_leaves_moved_tasks_where_they_are(db_session, plan, monkeypatch):
    """Moving them back would guess the human wants the old scheduling rather than the phase.
    The ids were returned at confirmation and a task can be moved again."""
    monkeypatch.setattr(pa, "_now", lambda: AFTER_PHASE_ONE)
    first, second, _ = _phases(db_session, plan)
    late = _task(db_session, plan, "Publish it", phase=first)
    pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    assert db_session.query(Task).get(late.id).phase_id == second.id

    pa.reopen_phase(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)

    assert db_session.query(Task).get(late.id).phase_id == second.id


def test_only_the_most_recently_closed_phase_can_reopen(db_session, plan):
    """A hole in the middle of the chain is not a state the plan can be in."""
    first, second, third = _phases(db_session, plan)
    first.status = PHASE_COMPLETE
    second.status = PHASE_COMPLETE
    third.status = PHASE_ACTIVE
    db_session.commit()

    with pytest.raises(ValueError, match="reopen 'Expansion and Scaling' first"):
        pa.reopen_phase(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)

    result = pa.reopen_phase(db_session, masterplan_id=plan.id, phase_id=second.id, user_id=USER)
    assert result["stepped_back"]["status"] == PHASE_PENDING


def test_the_last_phase_can_reopen_after_the_plan_completes(db_session, plan):
    phases = _phases(db_session, plan)
    for row in phases:
        row.status = PHASE_COMPLETE
    db_session.commit()

    result = pa.reopen_phase(db_session, masterplan_id=plan.id, phase_id=phases[2].id, user_id=USER)

    assert result["stepped_back"] is None
    assert result["plan_phase"] == 3


def test_reopening_a_phase_that_is_not_complete_is_refused(db_session, plan):
    first = _phases(db_session, plan)[0]
    with pytest.raises(ValueError, match="nothing to reopen"):
        pa.reopen_phase(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)


def test_reopening_clears_an_old_dismissal(db_session, plan, monkeypatch):
    """A reopened phase is a fresh question."""
    monkeypatch.setattr(pa, "_now", lambda: MID_PHASE_ONE)
    first = _phases(db_session, plan)[0]
    _task(db_session, plan, "Write the framework", phase=first, status="completed")
    pa.dismiss_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)
    pa.confirm_phase_advance(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)

    pa.reopen_phase(db_session, masterplan_id=plan.id, phase_id=first.id, user_id=USER)

    assert pa.propose_phase_advance(db_session, masterplan_id=plan.id, user_id=USER, now=MID_PHASE_ONE)["proposed"] is True
