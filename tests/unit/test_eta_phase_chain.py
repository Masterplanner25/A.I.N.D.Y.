"""The plan's sequential floor moves from the phases-as-tasks to `plan_phases`.

`STRATEGY_LAYER_SPEC` §8 step 3. `_project_days` imposes a floor of `critical_depth /
min(velocity, 1.0)` days — a dependency chain is sequential and cannot be parallelised away.
Until now that depth came from tasks 12→13→14→15→16, the five Genesis phases wearing task rows.

★ **This is the reason the retirement could not happen in step 2.** Delete those rows while
`critical_depth` still comes only from the task graph and the depth collapses to 1, the floor
vanishes, and the plan projects as though all five phases could run at once. The source has to
move first — in the same change that removes the rows, which is what makes step 3 atomic.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import eta_service
from apps.masterplan.services.strategy_layer_seed import seed_strategy_layer
from apps.masterplan.strategy_layer import PHASE_COMPLETE, PlanPhase

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()

STRUCTURE = {
    "phases": [
        {"name": "Foundation Building", "duration_months": 12},
        {"name": "Platform Development", "duration_months": 12},
        {"name": "Expansion and Scaling", "duration_months": 12},
        {"name": "Optimization and Feedback", "duration_months": 12},
        {"name": "Sustainability and Growth", "duration_months": 12},
    ]
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


# ── the depth itself ──────────────────────────────────────────────────────────────────

def test_a_chain_of_five_phases_has_depth_five(db_session, plan):
    seed_strategy_layer(db_session, masterplan_id=plan.id)

    assert eta_service._phase_chain_depth(db_session, plan.id) == 5


def test_depth_walks_the_edge_not_the_row_count(db_session, plan):
    """★ `ordinal` is a display concern; the edge is what carries the order.

    Two unchained phases are two things that can happen at once, and the floor must say so
    even though the row count is identical.
    """
    for ordinal, name in enumerate(("One", "Two"), start=1):
        db_session.add(
            PlanPhase(masterplan_id=plan.id, user_id=USER, name=name, ordinal=ordinal)
        )
    db_session.commit()

    assert eta_service._phase_chain_depth(db_session, plan.id) == 1


def test_completed_phases_leave_the_chain(db_session, plan):
    """The floor is about work that remains."""
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    rows = db_session.query(PlanPhase).order_by(PlanPhase.ordinal).all()
    for row in rows[:2]:
        row.status = PHASE_COMPLETE
    db_session.commit()

    assert eta_service._phase_chain_depth(db_session, plan.id) == 3


def test_a_plan_with_no_phases_has_no_phase_depth(db_session, plan):
    """Nothing changes for a plan that has not been seeded."""
    assert eta_service._phase_chain_depth(db_session, plan.id) == 0


def test_a_cycle_does_not_recurse_forever(db_session, plan):
    """Not expected — the seeder builds a single chain — but a malformed graph must terminate."""
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    rows = db_session.query(PlanPhase).order_by(PlanPhase.ordinal).all()
    rows[0].depends_on_phase_id = rows[-1].id
    db_session.commit()

    assert eta_service._phase_chain_depth(db_session, plan.id) >= 1


# ── ★ how it reaches the projection ───────────────────────────────────────────────────

def test_the_phase_chain_raises_the_floor(db_session, plan):
    """★ The assertion the retirement depends on.

    With the phases-as-tasks gone, the task graph reports depth 1. The phase chain has to put
    it back, or the plan projects as though all five phases could run at once.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)
    task_only = {"critical_depth": 1, "total": 3, "completed": 0}

    scoped = eta_service._apply_phase_chain_depth(db_session, plan, task_only)

    assert scoped["critical_depth"] == 5
    assert scoped["critical_depth_source"] == "plan_phases"


def test_a_deeper_task_chain_wins(db_session, plan):
    """`max`, not replacement.

    Tasks can still form chains inside a phase, and taking the larger keeps whichever
    constraint actually binds.
    """
    seed_strategy_layer(db_session, masterplan_id=plan.id)

    scoped = eta_service._apply_phase_chain_depth(
        db_session, plan, {"critical_depth": 9, "total": 12, "completed": 0}
    )

    assert scoped["critical_depth"] == 9
    assert "critical_depth_source" not in scoped


def test_an_unseeded_plan_is_untouched(db_session, plan):
    """A plan with no `plan_phases` behaves exactly as before."""
    original = {"critical_depth": 3, "total": 5, "completed": 1}

    assert eta_service._apply_phase_chain_depth(db_session, plan, original) == original


def test_a_missing_scope_stays_missing(db_session, plan):
    """`None` means the graph had no nodes; the caller falls back to legacy counts."""
    seed_strategy_layer(db_session, masterplan_id=plan.id)

    assert eta_service._apply_phase_chain_depth(db_session, plan, None) is None


def test_the_floor_survives_a_broken_phase_read(db_session, plan, monkeypatch):
    """ETA is a projection, not a gate. A failure here must degrade, not raise."""
    def _boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(eta_service, "_phase_chain_depth", _boom)
    original = {"critical_depth": 2, "total": 4, "completed": 0}

    assert eta_service._apply_phase_chain_depth(db_session, plan, original) == original


# ── and what it means for the projection ──────────────────────────────────────────────

def test_a_depth_of_five_pushes_the_date_out(db_session):
    """The floor is `critical_depth / min(velocity, 1.0)` days, and it beats throughput here."""
    fast_throughput = eta_service._project_days(remaining=5, velocity=5.0, critical_depth=1)
    with_chain = eta_service._project_days(remaining=5, velocity=5.0, critical_depth=5)

    assert fast_throughput == 1.0
    assert with_chain == 5.0, "the sequential floor did not bind"
