"""The facts an agent planner needs about the user's MasterPlan, with the real IDs.

Registered as the job `masterplan.planning_context` and read by the agent's planner-context
provider (`apps/agent/agents/runtime_extensions.py`) through `get_job`, the same route the KPI
snapshot takes, so no cross-app import is needed.

Why it exists (owner, 2026-09-26): asked to "create the tasks for the first two weeks … attached
to the right strategy in my MasterPlan", the planner planned a `memory.recall` "so tasks can be
attached to the right strategy_id" and then passed `strategy_id: "aindy-runtime-gtm"`, an ID it
invented, to five `task.create` steps (run `abf834d4`). A step cannot read an earlier step's
result (FR-46), and no tool lists strategies, so the ID has to be in the prompt before the plan is
written. Only OPEN strategies (proposed / active) are listed: a finished one is not somewhere new
work goes.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

OPEN_STRATEGY_STATUSES = ("proposed", "active")


def goal_lines(*, user_id: Any, db: Session) -> list[dict[str, Any]]:
    """The person's active goals for the planner, one each (GOALS_LAYER_SPEC §6, decision 5): name, how it is measured,
    and its progress, or why it has none."""
    from apps.masterplan.services.goal_seeding import _view
    from apps.masterplan.models import Goal

    rows = (db.query(Goal).filter(Goal.user_id == user_id, Goal.status == "active")
            .order_by(Goal.priority.desc(), Goal.created_at.asc()).all())
    goals = []
    for goal in rows:
        view = _view(db, goal)
        goals.append({"name": view["name"], "measure": view["measure"], "progress": view["progress"],
                      "objectives": [o["name"] for o in view["objectives"]], "target_value": view["target_value"],
                      "unit": view["unit"], "target_date": (view["target_date"] or "")[:10] or None})
    return goals


def build_planning_context(*, user_id: Any, db: Session) -> dict[str, Any] | None:
    """The active plan, its current phase, its open strategies and the person's active goals. Goals belong to the
    person, not the plan, so they are listed without an active plan too. None when there is neither."""
    from apps.masterplan.models import MasterPlan
    from apps.masterplan.services import strategy_layer_service as layer
    from apps.masterplan.services.phase_advance import frontier_phase, strategy_task_counts
    from apps.masterplan.strategy_layer import PlanPhase

    plan = (
        db.query(MasterPlan)
        .filter(MasterPlan.user_id == user_id, MasterPlan.is_active.is_(True))
        .first()
    )
    goals = goal_lines(user_id=user_id, db=db)
    if plan is None:
        return {"masterplan_id": None, "current_phase": None, "strategies": [], "goals": goals} if goals else None

    phases = layer.list_phases(db, masterplan_id=plan.id)
    phase_names = {p["id"]: p["name"] for p in phases}
    # The phase panel's notion of "current": the active phase, else the first pending one whose
    # dependency is met. On the live plan every phase is `pending`, so status alone finds none.
    rows = (
        db.query(PlanPhase)
        .filter(PlanPhase.masterplan_id == plan.id)
        .order_by(PlanPhase.ordinal.asc(), PlanPhase.created_at.asc())
        .all()
    )
    current = frontier_phase(rows)
    objective_names = {o["id"]: o["name"] for o in layer.list_objectives(db, masterplan_id=plan.id)}
    counts = strategy_task_counts(db, masterplan_id=plan.id, user_id=user_id)

    strategies = []
    for s in layer.list_strategies(db, masterplan_id=plan.id):
        if s["status"] not in OPEN_STRATEGY_STATUSES:
            continue
        c = counts.get(s["id"]) or {}
        strategies.append({
            "id": s["id"],
            "name": s["name"],
            "status": s["status"],
            "objective": objective_names.get(s["objective_id"]),
            "phase": phase_names.get(s["phase_id"]),
            "tasks_total": int(c.get("total") or 0),
            "tasks_completed": int(c.get("completed") or 0),
        })

    return {
        "masterplan_id": plan.id,
        "current_phase": {"id": current.id, "name": current.name} if current else None,
        "strategies": strategies,
        "goals": goals,
    }
