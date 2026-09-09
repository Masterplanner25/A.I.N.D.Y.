"""Seeding a plan's objectives and phases from what Genesis already produced.

`STRATEGY_LAYER_SPEC` §8, step 2. Genesis emits both axes and always has: three `core_domains`
and five `phases` sit in `structure_json` on every locked plan. The phases were materialised as
**tasks** — never actionable, permanently `pending` — and the domains were rendered as
read-only text and stored nowhere.

★ **The load-bearing assertion in this file is what seeding does NOT do.** §8 says the five
phase-as-task rows should be deleted, and they should — but not here. The live chain
12→13→14→15→16 feeds `eta_service` → `critical_depth`, which sets a **sequential floor** on the
plan's ETA. Delete those tasks before anything reads `plan_phases` and the floor vanishes: the
plan projects as though all five phases could run at once.

So §8's warning has a converse. *Nothing may read `plan_phases` until the rows have moved*, and
**nothing may stop reading the tasks until something reads `plan_phases`.** The delete belongs
with the rewire.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services.strategy_layer_seed import (
    attach_tasks_to_phases,
    seed_strategy_layer,
)
from apps.masterplan.strategy_layer import PlanObjective, PlanPhase
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()

# The live plan's own shape, so the test exercises what actually has to migrate.
STRUCTURE = {
    "core_domains": [
        {"name": "Ethical AI Framework", "intent": "To establish guidelines and standards."},
        {"name": "Partnership Development", "intent": "To create strategic alliances."},
        {"name": "Platform Enablement", "intent": "To build and maintain platforms."},
    ],
    "phases": [
        {"name": "Foundation Building", "description": "Establish the framework.", "duration_months": 12},
        {"name": "Platform Development", "description": "Develop and deploy.", "duration_months": 12},
        {"name": "Expansion and Scaling", "description": "Scale the ecosystem.", "duration_months": 12},
        {"name": "Optimization and Feedback", "description": "Refine systems.", "duration_months": 12},
        {"name": "Sustainability and Growth", "description": "Ensure sustainability.", "duration_months": 12},
    ],
}


@pytest.fixture
def plan(db_session):
    row = MasterPlan(
        start_date=datetime(2026, 1, 1), duration_years=5.0,
        target_date=datetime(2031, 1, 1), user_id=USER, status="locked",
        structure_json=STRUCTURE,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _phase_task(db, plan, name, *, status="pending"):
    row = Task(name=name, user_id=USER, status=status, priority="medium",
               masterplan_id=plan.id, duration=1.0)
    db.add(row)
    db.commit()
    return row


# ── what Genesis already produced becomes rows ────────────────────────────────────────

def test_core_domains_become_objectives(db_session, plan):
    """They are objectives in everything but name, and were stored nowhere."""
    result = seed_strategy_layer(db_session, masterplan_id=plan.id)

    rows = db_session.query(PlanObjective).order_by(PlanObjective.ordinal).all()
    assert result["objectives"] == 3
    assert [r.name for r in rows] == [
        "Ethical AI Framework", "Partnership Development", "Platform Enablement"
    ]
    assert rows[0].intent.startswith("To establish guidelines")


def test_phases_become_phases_in_order(db_session, plan):
    seed_strategy_layer(db_session, masterplan_id=plan.id)

    rows = db_session.query(PlanPhase).order_by(PlanPhase.ordinal).all()
    assert [r.name for r in rows] == [p["name"] for p in STRUCTURE["phases"]]
    assert [r.ordinal for r in rows] == [1, 2, 3, 4, 5]
    assert all(r.duration_months == 12 for r in rows)


def test_the_phase_order_is_carried_as_an_explicit_chain(db_session, plan):
    """★ Not as `ordinal`.

    The order sets the plan's sequential ETA floor. An ordinal is a display concern that any
    reorder would quietly change; an edge survives one.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    rows = db_session.query(PlanPhase).order_by(PlanPhase.ordinal).all()

    assert rows[0].depends_on_phase_id is None
    for earlier, later in zip(rows, rows[1:]):
        assert later.depends_on_phase_id == earlier.id


# ── ★ what seeding must NOT do ────────────────────────────────────────────────────────

def test_seeding_does_not_delete_the_phase_as_task_rows(db_session, plan):
    """★ The load-bearing one.

    Those five tasks carry the dependency chain `eta_service` turns into `critical_depth`.
    Removing them before anything reads `plan_phases` collapses the chain to 1 and the plan
    projects as if all five phases could run at once. The delete belongs with the rewire.
    """
    for phase in STRUCTURE["phases"]:
        _phase_task(db_session, plan, phase["name"])

    seed_strategy_layer(db_session, masterplan_id=plan.id)

    assert db_session.query(Task).filter(Task.masterplan_id == plan.id).count() == 5


def test_seeding_leaves_the_task_dependency_chain_untouched(db_session, plan):
    first = _phase_task(db_session, plan, "Foundation Building")
    second = _phase_task(db_session, plan, "Platform Development", status="blocked")
    second.depends_on = [{"task_id": first.id, "dependency_type": "hard"}]
    db_session.commit()

    seed_strategy_layer(db_session, masterplan_id=plan.id)
    db_session.expire_all()

    assert db_session.query(Task).filter(Task.id == second.id).first().depends_on == [
        {"task_id": first.id, "dependency_type": "hard"}
    ]


# ── idempotency, because this runs at lock AND as a backfill ──────────────────────────

def test_seeding_twice_creates_nothing_the_second_time(db_session, plan):
    """The same call seeds a new plan at lock and backfills one locked before it existed."""
    first = seed_strategy_layer(db_session, masterplan_id=plan.id)
    second = seed_strategy_layer(db_session, masterplan_id=plan.id)

    assert (first["objectives"], first["phases"]) == (3, 5)
    assert (second["objectives"], second["phases"]) == (0, 0)
    assert db_session.query(PlanPhase).count() == 5


def test_a_partial_seed_completes_rather_than_starting_a_second_chain(db_session, plan):
    """A half-seeded plan must end up with one chain, not two disconnected ones."""
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    db_session.query(PlanPhase).filter(PlanPhase.ordinal >= 4).delete(synchronize_session=False)
    db_session.commit()

    seed_strategy_layer(db_session, masterplan_id=plan.id)
    rows = db_session.query(PlanPhase).order_by(PlanPhase.ordinal).all()

    assert len(rows) == 5
    roots = [r for r in rows if r.depends_on_phase_id is None]
    assert len(roots) == 1, "a second chain was started"


# ── plans with nothing to seed ────────────────────────────────────────────────────────

def test_a_plan_with_no_structure_seeds_nothing_and_does_not_raise(db_session):
    """An imported or hand-made plan legitimately has neither axis."""
    row = MasterPlan(
        start_date=datetime(2026, 1, 1), duration_years=1.0,
        target_date=datetime(2027, 1, 1), user_id=USER, status="locked", structure_json={},
    )
    db_session.add(row)
    db_session.commit()

    result = seed_strategy_layer(db_session, masterplan_id=row.id)

    assert (result["objectives"], result["phases"]) == (0, 0)


def test_a_missing_plan_is_reported_not_raised(db_session):
    assert seed_strategy_layer(db_session, masterplan_id=999999)["reason"] == "plan not found"


# ── attaching real tasks ──────────────────────────────────────────────────────────────

def test_real_tasks_get_the_first_phase(db_session, plan):
    """Everything lands on phase 1 because nothing in the data says otherwise.

    Inventing a phase per task would be a guess wearing the shape of a migration — and a task
    can be moved afterwards, whereas a wrong guess recorded silently cannot be noticed.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    real = _phase_task(db_session, plan, "Fix Nodus Issues", status="completed")

    result = attach_tasks_to_phases(db_session, masterplan_id=plan.id)
    db_session.expire_all()

    assert result["attached"] == 1
    assert db_session.query(Task).filter(Task.id == real.id).first().phase_id == result["phase_id"]


def test_a_phase_wearing_a_task_row_is_skipped(db_session, plan):
    """★ Step 3's problem, not this one's.

    Attaching a phase-as-task to a phase would make the row that has to be deleted look like
    legitimate work scheduled into the layer replacing it.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    phase_row = _phase_task(db_session, plan, "Foundation Building")
    real = _phase_task(db_session, plan, "Fix Nodus Issues", status="completed")

    result = attach_tasks_to_phases(db_session, masterplan_id=plan.id)
    db_session.expire_all()

    assert (result["attached"], result["skipped_phase_rows"]) == (1, 1)
    assert db_session.query(Task).filter(Task.id == phase_row.id).first().phase_id is None
    assert db_session.query(Task).filter(Task.id == real.id).first().phase_id is not None


def test_attaching_is_idempotent(db_session, plan):
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    _phase_task(db_session, plan, "Fix Nodus Issues", status="completed")

    attach_tasks_to_phases(db_session, masterplan_id=plan.id)
    second = attach_tasks_to_phases(db_session, masterplan_id=plan.id)

    assert second["attached"] == 0


def test_attaching_without_phases_does_nothing(db_session, plan):
    _phase_task(db_session, plan, "Fix Nodus Issues", status="completed")

    result = attach_tasks_to_phases(db_session, masterplan_id=plan.id)

    assert result["attached"] == 0
    assert result["reason"]


def test_attaching_falls_back_to_the_plans_owner(db_session, plan):
    """★ The only way this could silently do nothing.

    The task syscalls refuse an unauthenticated tenant, and this function is non-fatal — so a
    call without `user_id` would attach nothing, log a warning, and report success. Deriving
    the owner from the plan removes that path.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    real = _phase_task(db_session, plan, "Fix Nodus Issues", status="completed")

    result = attach_tasks_to_phases(db_session, masterplan_id=plan.id)  # no user_id
    db_session.expire_all()

    assert result["attached"] == 1
    assert db_session.query(Task).filter(Task.id == real.id).first().phase_id is not None


def test_a_plan_with_no_owner_says_so_rather_than_attaching_nothing_quietly(db_session):
    """An ownerless plan cannot act as anyone, and the caller is told."""
    row = MasterPlan(
        start_date=datetime(2026, 1, 1), duration_years=1.0,
        target_date=datetime(2027, 1, 1), user_id=None, status="locked",
        structure_json=STRUCTURE,
    )
    db_session.add(row)
    db_session.commit()
    seed_strategy_layer(db_session, masterplan_id=row.id)

    result = attach_tasks_to_phases(db_session, masterplan_id=row.id)

    assert result["attached"] == 0
    assert "owner" in result["reason"]


# ── ★ retiring the phases-as-tasks, and what stops it ─────────────────────────────────
#
# `STRATEGY_LAYER_SPEC` §8 step 3. These rows are not work — never actionable, never
# completable — and leaving them keeps the exact ambiguity the layer exists to remove. §8 says
# to write this by hand and read it before running it; `apply=False` is that made mechanical.

from apps.masterplan.services.strategy_layer_seed import retire_phase_as_task_rows  # noqa: E402


def _seeded_plan_with_phase_tasks(db, plan):
    seed_strategy_layer(db, masterplan_id=plan.id)
    return [_phase_task(db, plan, p["name"]) for p in STRUCTURE["phases"]]


def test_retiring_is_a_dry_run_by_default(db_session, plan):
    """★ `apply=False` is §8's "read it before running it", made mechanical."""
    _seeded_plan_with_phase_tasks(db_session, plan)

    report = retire_phase_as_task_rows(db_session, masterplan_id=plan.id)

    assert report["candidate_count"] == 5
    assert report["retired"] == 0
    assert report["applied"] is False
    assert db_session.query(Task).filter(Task.masterplan_id == plan.id).count() == 5


def test_the_dry_run_names_every_row_it_would_delete(db_session, plan):
    """A count asks for consent to something the reader cannot see."""
    _seeded_plan_with_phase_tasks(db_session, plan)

    names = {c["name"] for c in retire_phase_as_task_rows(db_session, masterplan_id=plan.id)["candidates"]}

    assert names == {p["name"] for p in STRUCTURE["phases"]}


def test_applying_removes_them(db_session, plan):
    _seeded_plan_with_phase_tasks(db_session, plan)
    real = _phase_task(db_session, plan, "Fix Nodus Issues", status="completed")

    report = retire_phase_as_task_rows(db_session, masterplan_id=plan.id, apply=True)
    db_session.expire_all()

    assert (report["retired"], report["applied"]) == (5, True)
    remaining = db_session.query(Task).filter(Task.masterplan_id == plan.id).all()
    assert [t.id for t in remaining] == [real.id]


def test_it_refuses_when_a_phase_named_task_is_completed(db_session, plan):
    """★ A completed row is real work someone did, whatever it is named.

    WCU accrues from completed tasks, so deleting one retroactively reduces the work done.
    Reported as a refusal rather than filtered out: it means an assumption behind this
    migration is wrong for that plan.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    _phase_task(db_session, plan, "Foundation Building", status="completed")
    _phase_task(db_session, plan, "Platform Development")

    report = retire_phase_as_task_rows(db_session, masterplan_id=plan.id, apply=True)

    assert report["retired"] == 0
    assert any("completed" in r for r in report["refusals"])
    assert db_session.query(Task).filter(Task.masterplan_id == plan.id).count() == 2


def test_it_refuses_when_a_real_task_depends_on_one(db_session, plan):
    """★ Deleting a row a real task is blocked behind would silently unblock it.

    Dependencies *among* the retiring rows are the chain being removed wholesale, which is
    fine. A dependent outside the set is not.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    phase_row = _phase_task(db_session, plan, "Foundation Building")
    real = _phase_task(db_session, plan, "Write the thing", status="blocked")
    real.depends_on = [{"task_id": phase_row.id, "dependency_type": "hard"}]
    db_session.commit()

    report = retire_phase_as_task_rows(db_session, masterplan_id=plan.id, apply=True)

    assert report["retired"] == 0
    assert any("depend" in r for r in report["refusals"])
    assert db_session.query(Task).filter(Task.id == phase_row.id).first() is not None


def test_the_chain_among_the_retiring_rows_does_not_block_it(db_session, plan):
    """The five phases depend on each other by design; that is the chain being removed."""
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    rows = [_phase_task(db_session, plan, p["name"]) for p in STRUCTURE["phases"]]
    for earlier, later in zip(rows, rows[1:]):
        later.depends_on = [{"task_id": earlier.id, "dependency_type": "hard"}]
    db_session.commit()

    report = retire_phase_as_task_rows(db_session, masterplan_id=plan.id, apply=True)

    assert report["refusals"] == []
    assert report["retired"] == 5


def test_it_refuses_before_the_layer_is_seeded(db_session, plan):
    """★ Nothing may stop reading the tasks until something else owns the representation."""
    for phase in STRUCTURE["phases"]:
        _phase_task(db_session, plan, phase["name"])

    report = retire_phase_as_task_rows(db_session, masterplan_id=plan.id, apply=True)

    assert report["retired"] == 0
    assert "seed" in report["reason"]
    assert db_session.query(Task).filter(Task.masterplan_id == plan.id).count() == 5


def test_a_task_that_merely_resembles_a_phase_is_left_alone(db_session, plan):
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    _phase_task(db_session, plan, "Foundation Building Notes")

    report = retire_phase_as_task_rows(db_session, masterplan_id=plan.id, apply=True)

    assert report["candidate_count"] == 0
    assert db_session.query(Task).filter(Task.masterplan_id == plan.id).count() == 1
