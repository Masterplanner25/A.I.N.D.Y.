"""The strategy layer — objectives, phases and strategies.

`STRATEGY_LAYER_SPEC.md`. The owner's three-layer model:

> MasterPlan + goals → strategies (temporary, executable, failable, learnable, refinable) → tasks

The layer already existed in this system; it was stored as tasks. On the live plan, "tasks"
12–16 are the five Genesis phases wearing task rows — never actionable, never completable,
permanently `pending`.

★ **Three invariants carry the meaning**, and each is asserted below rather than described:

1. **A displaced strategy has no outcome, ever.** *"We tried publishing and it did not move the
   objective"* and *"we never published because we did the partnership instead"* are different
   evidence, and a success rate over a set that mixes them is meaningless.
2. **Abandoning does not cascade to completed tasks.** You did the work; the approach is what
   failed — and WCU accrues from completed tasks, so cancelling them would retroactively reduce
   the work you did.
3. **`phase_id` is scheduling, `objective_id` is ownership.** Moving between phases is ordinary
   replanning; changing the objective changes what the strategy is for.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import strategy_layer_service as svc
from apps.masterplan.strategy_layer import PlanStrategy
from apps.tasks.models import Task

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()


@pytest.fixture
def plan(db_session):
    row = MasterPlan(
        start_date=datetime(2026, 1, 1),
        duration_years=5.0,
        target_date=datetime(2031, 1, 1),
        user_id=USER,
        status="locked",
        structure_json={},
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _objective(db, plan, name="Ethical AI Framework"):
    return svc.create_objective(
        db, user_id=USER, masterplan_id=plan.id, name=name,
        intent="to establish guidelines and standards",
    )


def _strategy(db, plan, **kwargs):
    payload = {"name": "Publish weekly", **kwargs}
    return svc.create_strategy(db, user_id=USER, masterplan_id=plan.id, **payload)


def _task(db, *, name, status, strategy_id):
    row = Task(
        name=name, user_id=USER, status=status, priority="medium",
        strategy_id=strategy_id, duration=2.0,
    )
    db.add(row)
    db.commit()
    return row


# ── two axes, not one chain ───────────────────────────────────────────────────────────

def test_a_strategy_is_owned_by_an_objective_and_scheduled_into_a_phase(db_session, plan):
    objective = _objective(db_session, plan)
    phase = svc.create_phase(db_session, user_id=USER, masterplan_id=plan.id, name="Foundation")

    strategy = _strategy(
        db_session, plan, objective_id=objective["id"], phase_id=phase["id"]
    )

    assert strategy["objective_id"] == objective["id"]
    assert strategy["phase_id"] == phase["id"]


def test_moving_between_phases_is_ordinary(db_session, plan):
    """★ Owner: "maybe some things move phases."

    `phase_id` is scheduling, not ownership — which is what makes this a refine rather than a
    plan rewrite. It does not touch the objective, and it does not end the strategy.
    """
    objective = _objective(db_session, plan)
    first = svc.create_phase(db_session, user_id=USER, masterplan_id=plan.id, name="One", ordinal=1)
    second = svc.create_phase(db_session, user_id=USER, masterplan_id=plan.id, name="Two", ordinal=2)
    strategy = _strategy(db_session, plan, objective_id=objective["id"], phase_id=first["id"])

    moved = svc.move_strategy_to_phase(
        db_session, strategy_id=strategy["id"], phase_id=second["id"]
    )

    assert moved["phase_id"] == second["id"]
    assert moved["objective_id"] == objective["id"]
    assert moved["status"] == strategy["status"]


def test_a_strategy_can_be_unscheduled(db_session, plan):
    strategy = _strategy(db_session, plan)
    assert svc.move_strategy_to_phase(
        db_session, strategy_id=strategy["id"], phase_id=None
    )["phase_id"] is None


def test_the_phase_dependency_edge_is_carried_explicitly(db_session, plan):
    """★ The order is load-bearing, not presentational.

    The live chain 12→13→14→15→16 feeds `eta_service` → `critical_depth`, which sets a
    sequential floor on the plan's ETA. Inferring order from `ordinal` alone would lose it the
    moment anything reordered.
    """
    first = svc.create_phase(db_session, user_id=USER, masterplan_id=plan.id, name="One", ordinal=1)
    second = svc.create_phase(
        db_session, user_id=USER, masterplan_id=plan.id, name="Two", ordinal=2,
        depends_on_phase_id=first["id"],
    )

    assert second["depends_on_phase_id"] == first["id"]


# ── ★ invariant 1: displaced has no outcome ───────────────────────────────────────────

def test_abandoning_records_a_result(db_session, plan):
    """Tried it; it did not work."""
    strategy = _strategy(db_session, plan)
    result = svc.abandon_strategy(db_session, strategy_id=strategy["id"], note="no traction")

    assert result["status"] == "abandoned"
    assert result["outcome"] == "did_not_work"


def test_displacing_records_a_choice_and_no_outcome(db_session, plan):
    """★ Never tried, so there is nothing to judge.

    A displaced strategy carrying a verdict would be indistinguishable from one that failed,
    which is the collapse this layer exists to prevent.
    """
    strategy = _strategy(db_session, plan)
    result = svc.displace_strategy(
        db_session, strategy_id=strategy["id"], note="did the partnership instead"
    )

    assert result["status"] == "displaced"
    assert result["outcome"] is None


def test_a_displaced_strategy_cannot_be_given_an_outcome(db_session, plan):
    strategy = _strategy(db_session, plan)
    svc.displace_strategy(db_session, strategy_id=strategy["id"])

    with pytest.raises(ValueError, match="never tried"):
        svc.conclude_strategy(db_session, strategy_id=strategy["id"], outcome="worked")


def test_displacing_clears_an_outcome_that_was_already_recorded(db_session, plan):
    """A strategy re-classified as displaced must not keep the verdict from when it wasn't."""
    strategy = _strategy(db_session, plan)
    svc.conclude_strategy(db_session, strategy_id=strategy["id"], outcome="did_not_work")

    result = svc.displace_strategy(db_session, strategy_id=strategy["id"])

    assert result["outcome"] is None


def test_abandoned_and_displaced_are_distinguishable_in_a_query(db_session, plan):
    """★ The reason the two exist separately.

    A success rate computed over a set that mixes "we tried and it failed" with "we never
    tried" is meaningless, and this is what makes filtering possible.
    """
    tried = _strategy(db_session, plan, name="Tried this")
    never = _strategy(db_session, plan, name="Never tried this")
    svc.abandon_strategy(db_session, strategy_id=tried["id"])
    svc.displace_strategy(db_session, strategy_id=never["id"])

    rows = svc.list_strategies(db_session, masterplan_id=plan.id)
    by_status = {row["status"]: row["name"] for row in rows}

    assert by_status["abandoned"] == "Tried this"
    assert by_status["displaced"] == "Never tried this"


def test_an_invented_outcome_is_refused(db_session, plan):
    strategy = _strategy(db_session, plan)
    with pytest.raises(ValueError):
        svc.conclude_strategy(db_session, strategy_id=strategy["id"], outcome="great")


# ── ★ invariant 2: completed work survives abandonment ────────────────────────────────

def test_abandoning_releases_incomplete_tasks_and_keeps_completed_ones(db_session, plan):
    """★ You did the work; the approach is what failed.

    WCU accrues from completed tasks, so cancelling or unlinking them would retroactively
    reduce the work you did — and it would contradict `masterplan_execution_service`, which
    already refuses to replace a plan's tasks when any are completed.
    """
    strategy = _strategy(db_session, plan)
    done = _task(db_session, name="Wrote the piece", status="completed", strategy_id=strategy["id"])
    todo = _task(db_session, name="Write another", status="pending", strategy_id=strategy["id"])

    result = svc.abandon_strategy(db_session, strategy_id=strategy["id"])
    db_session.expire_all()

    assert result["tasks_released"] == 1
    assert db_session.query(Task).filter(Task.id == done.id).first().strategy_id == strategy["id"]
    assert db_session.query(Task).filter(Task.id == todo.id).first().strategy_id is None


def test_a_released_task_is_not_cancelled(db_session, plan):
    """It returns to the plan unattached — it does not disappear."""
    strategy = _strategy(db_session, plan)
    todo = _task(db_session, name="Write another", status="pending", strategy_id=strategy["id"])

    svc.abandon_strategy(db_session, strategy_id=strategy["id"])
    db_session.expire_all()

    assert db_session.query(Task).filter(Task.id == todo.id).first().status == "pending"


def test_displacing_releases_tasks_the_same_way(db_session, plan):
    strategy = _strategy(db_session, plan)
    _task(db_session, name="Never started", status="pending", strategy_id=strategy["id"])

    assert svc.displace_strategy(db_session, strategy_id=strategy["id"])["tasks_released"] == 1


# ── emergent strategies: the thing that currently leaves no trace ─────────────────────

def test_an_emergent_strategy_starts_active_not_proposed(db_session, plan):
    """It is being recorded after the fact; "proposed" would be a lie about its own history."""
    strategy = _strategy(db_session, plan, name="Wrote a book too", origin="emergent")

    assert strategy["origin"] == "emergent"
    assert strategy["status"] == "active"
    assert strategy["started_at"]


def test_an_emergent_strategy_with_no_objective_is_legal(db_session, plan):
    """★ The most informative state the layer can hold.

    You did something the plan never anticipated, and it worked. Today that leaves no trace
    anywhere — §5's "the plan under-described reality".
    """
    strategy = _strategy(db_session, plan, name="Partnership", origin="emergent")

    assert strategy["objective_id"] is None


def test_unhoused_emergent_strategies_are_findable(db_session, plan):
    """This is what a *revise* is derived from.

    §5's divergence table: an emergent strategy serving an existing objective is a refine — a
    route nobody wrote down. One serving no objective is a revise: the plan is now aiming
    somewhere it does not say.
    """
    objective = _objective(db_session, plan)
    _strategy(db_session, plan, name="Housed", origin="emergent", objective_id=objective["id"])
    _strategy(db_session, plan, name="Unhoused", origin="emergent")
    _strategy(db_session, plan, name="Planned and unhoused", origin="planned")

    rows = svc.unhoused_emergent_strategies(db_session, masterplan_id=plan.id)

    # Only the emergent one with no objective — a planned strategy without an objective is an
    # incomplete plan, not a divergence.
    assert [row["name"] for row in rows] == ["Unhoused"]


def test_an_invented_origin_is_refused(db_session, plan):
    with pytest.raises(ValueError):
        _strategy(db_session, plan, origin="spontaneous")


# ── lifecycle guards ──────────────────────────────────────────────────────────────────

def test_a_concluded_strategy_cannot_be_restarted(db_session, plan):
    """A strategy that is over is over. Restarting one is a new strategy."""
    strategy = _strategy(db_session, plan)
    svc.conclude_strategy(db_session, strategy_id=strategy["id"], outcome="worked")

    with pytest.raises(ValueError, match="cannot be started again"):
        svc.start_strategy(db_session, strategy_id=strategy["id"])


def test_a_nameless_row_is_refused(db_session, plan):
    for factory in (
        lambda: svc.create_objective(db_session, user_id=USER, masterplan_id=plan.id, name="  "),
        lambda: svc.create_phase(db_session, user_id=USER, masterplan_id=plan.id, name=""),
        lambda: _strategy(db_session, plan, name="   "),
    ):
        with pytest.raises(ValueError):
            factory()


def test_strategies_can_be_listed_by_objective_and_by_phase(db_session, plan):
    objective = _objective(db_session, plan)
    other = _objective(db_session, plan, name="Revenue")
    phase = svc.create_phase(db_session, user_id=USER, masterplan_id=plan.id, name="One")
    _strategy(db_session, plan, name="A", objective_id=objective["id"], phase_id=phase["id"])
    _strategy(db_session, plan, name="B", objective_id=other["id"])

    assert [s["name"] for s in svc.list_strategies(
        db_session, masterplan_id=plan.id, objective_id=objective["id"]
    )] == ["A"]
    assert [s["name"] for s in svc.list_strategies(
        db_session, masterplan_id=plan.id, phase_id=phase["id"]
    )] == ["A"]


# ── nothing reads it yet, which is deliberate ─────────────────────────────────────────

def test_the_tables_start_empty_and_no_existing_path_writes_them(db_session, plan):
    """★ §8: nothing may read `plan_phases` until the six live rows have moved.

    Otherwise the plan briefly has five phases in one table and five phases-as-tasks in
    another — the exact condition the spec is complaining about, added to rather than removed.
    """
    assert svc.list_phases(db_session, masterplan_id=plan.id) == []
    assert svc.list_objectives(db_session, masterplan_id=plan.id) == []
    assert db_session.query(PlanStrategy).count() == 0
