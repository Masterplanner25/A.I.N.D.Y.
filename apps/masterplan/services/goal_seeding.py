"""Goals proposed from the person's plan, and the person's say over them (GOALS_LAYER_SPEC §5, phase B; decided
2026-11-09).

A proposal is a goal with status ``proposed``. Every reader of goals (the loop, the gate, agent ranking, the planner)
reads ``active`` goals only, so a proposal acts on nothing until the person confirms it (decision 1). A dropped
proposal stays ``dropped`` and is never proposed again.

From the active plan:
- **the anchor** → one goal, ``measure=anchor``, with its number, unit and date;
- **each success criterion** → one goal, with the objectives that plainly serve it suggested as links
  (``measure=objectives``), or none (``measure=declared``, decision 2).

Proposing is idempotent: a candidate already present for that plan, in any status, is not proposed again. It runs at
plan lock, and on the first read of the overview for a plan locked before this existed.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from AINDY.utils.uuid_utils import normalize_uuid
from apps.masterplan.models import Goal, GoalObjective, MasterPlan, PlanObjective
from apps.masterplan.services.goal_service import (
    MEASURE_ANCHOR,
    MEASURE_DECLARED,
    MEASURE_OBJECTIVES,
    _apply_measure,
    _get_or_create_goal_state,
    _serialize_goal,
)

PROPOSED = "proposed"
ACTIVE = "active"
DROPPED = "dropped"
COMPLETED = "completed"
ANCHOR_PRIORITY = 0.7
CRITERION_PRIORITY = 0.5
_STEM = 5  # "platforms"/"platform", "enabling"/"enablement", "partnerships"/"partnership"
_SKIP = {"and", "the", "for", "with", "from", "into", "that", "this", "development", "successful", "establishment",
         "formation", "positive", "sustainable", "widely"}


def _stems(text: str) -> set[str]:
    return {w[:_STEM] for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 3 and w not in _SKIP}


def suggest_objectives(criterion: str, objectives: list[dict]) -> list[str]:
    """The objectives whose name shares a word (by its first five letters) with the criterion. A suggestion the person
    confirms or changes, never a link made silently."""
    wanted = _stems(criterion)
    return [o["id"] for o in objectives if wanted & _stems(o["name"])]


def _active_plan(db, user_id) -> MasterPlan | None:
    return (db.query(MasterPlan)
            .filter(MasterPlan.user_id == normalize_uuid(user_id), MasterPlan.is_active.is_(True))
            .first())


def _criteria(plan: MasterPlan) -> list[str]:
    structure = plan.structure_json if isinstance(plan.structure_json, dict) else {}
    criteria = structure.get("success_criteria") or (structure.get("draft") or {}).get("success_criteria") or []
    return [" ".join(str(c).split()) for c in criteria if isinstance(c, str) and c.strip()]


def _objectives(db, plan_id: int) -> list[dict]:
    rows = (db.query(PlanObjective.id, PlanObjective.name).filter(PlanObjective.masterplan_id == plan_id)
            .order_by(PlanObjective.ordinal).all())
    return [{"id": str(i), "name": n} for i, n in rows]


def propose_goals(db, user_id, *, plan: MasterPlan | None = None) -> list[dict]:
    """Propose the active plan's anchor and success criteria as goals, each once. Returns the new proposals."""
    plan = plan or _active_plan(db, user_id)
    if plan is None:
        return []
    uid = normalize_uuid(user_id)
    existing = {(g.source, (g.name or "").strip().lower())
                for g in db.query(Goal.source, Goal.name).filter(Goal.user_id == uid, Goal.masterplan_id == plan.id)}
    objectives = _objectives(db, plan.id)
    made: list[Goal] = []

    def add(**fields) -> Goal | None:
        key = (fields["source"], fields["name"].strip().lower())
        if key in existing:
            return None
        goal = Goal(user_id=uid, masterplan_id=plan.id, status=PROPOSED, goal_type="strategic",
                    success_metric={}, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
                    **fields)
        db.add(goal)
        db.flush()
        existing.add(key)
        made.append(goal)
        return goal

    if plan.goal_value and plan.goal_unit:
        add(source="anchor", measure=MEASURE_ANCHOR, priority=ANCHOR_PRIORITY,
            name=(plan.goal_description or "").strip() or f"{plan.goal_value:g} {plan.goal_unit}",
            description=f"{plan.goal_value:,.0f} {plan.goal_unit}" + (f" by {plan.anchor_date:%Y-%m-%d}" if plan.anchor_date else ""),
            target_value=float(plan.goal_value), unit=str(plan.goal_unit), target_date=plan.anchor_date)
    for criterion in _criteria(plan):
        links = suggest_objectives(criterion, objectives)
        goal = add(source="success_criterion", measure=MEASURE_OBJECTIVES if links else MEASURE_DECLARED,
                   priority=CRITERION_PRIORITY, name=criterion, description=None)
        if goal is not None:
            for objective_id in links:
                db.add(GoalObjective(goal_id=goal.id, objective_id=objective_id))
    db.commit()
    return [_view(db, g) for g in made]


def _owned(db, user_id, goal_id) -> Goal:
    import uuid

    try:
        gid = uuid.UUID(str(goal_id))
    except (TypeError, ValueError):
        raise LookupError("goal not found") from None
    goal = db.query(Goal).filter(Goal.id == gid, Goal.user_id == normalize_uuid(user_id)).first()
    if goal is None:
        raise LookupError("goal not found")
    return goal


def _set_links(db, goal: Goal, objective_ids: list[str]) -> None:
    """Replace a goal's objective links with the person's choice, keeping only objectives they own. An anchor goal keeps
    its measure; any other goal is measured by its objectives when it has some, and declared when it has none."""
    owned = {str(i) for (i,) in db.query(PlanObjective.id).join(MasterPlan, MasterPlan.id == PlanObjective.masterplan_id)
             .filter(MasterPlan.user_id == goal.user_id, PlanObjective.id.in_([str(o) for o in objective_ids] or [""]))}
    db.query(GoalObjective).filter(GoalObjective.goal_id == goal.id).delete(synchronize_session=False)
    for objective_id in dict.fromkeys(str(o) for o in objective_ids):
        if objective_id in owned:
            db.add(GoalObjective(goal_id=goal.id, objective_id=objective_id))
    if goal.measure != MEASURE_ANCHOR:
        goal.measure = MEASURE_OBJECTIVES if owned else MEASURE_DECLARED


def _edit(db, goal: Goal, edits: dict[str, Any]) -> None:
    if edits.get("name"):
        goal.name = " ".join(str(edits["name"]).split())[:255]
    if "description" in edits and edits["description"] is not None:
        goal.description = str(edits["description"])
    if edits.get("priority") is not None:
        goal.priority = max(0.0, min(1.0, float(edits["priority"])))
    if edits.get("objective_ids") is not None:
        _set_links(db, goal, list(edits["objective_ids"]))
    goal.updated_at = datetime.now(timezone.utc)


def confirm_goal(db, user_id, goal_id, edits: dict[str, Any] | None = None) -> dict:
    """The person accepts a proposal, with any edits. It becomes active and is measured from now on."""
    goal = _owned(db, user_id, goal_id)
    if goal.status != PROPOSED:
        raise ValueError(f"only a proposed goal can be confirmed; this one is {goal.status}")
    _edit(db, goal, edits or {})
    goal.status = ACTIVE
    state = _get_or_create_goal_state(db, goal.id)
    _apply_measure(db, goal, state)
    db.commit()
    return _view(db, goal)


def drop_goal(db, user_id, goal_id) -> dict:
    """A proposal or goal the person does not want. Never proposed again."""
    goal = _owned(db, user_id, goal_id)
    goal.status = DROPPED
    goal.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _view(db, goal)


def update_goal(db, user_id, goal_id, edits: dict[str, Any]) -> dict:
    """Edit a goal. ``status: completed`` is how the person marks a goal done: a declared one (decision 2) or one measured
    through objectives (owner, 2026-11-09). Only an anchor goal completes from its number. ``status: active`` reopens
    one."""
    goal = _owned(db, user_id, goal_id)
    _edit(db, goal, edits)
    wanted = edits.get("status")
    if wanted is not None:
        if wanted not in (ACTIVE, COMPLETED):
            raise ValueError("status can be set to active or completed")
        if wanted == COMPLETED and goal.measure == MEASURE_ANCHOR:
            raise ValueError("an anchor goal completes from its number; any other goal is marked done")
        goal.status = wanted
    if goal.status == ACTIVE:
        _apply_measure(db, goal, _get_or_create_goal_state(db, goal.id))
    db.commit()
    return _view(db, goal)


def _view(db, goal: Goal) -> dict:
    from apps.masterplan.models import GoalState

    state = db.query(GoalState).filter(GoalState.goal_id == goal.id).first()
    view = _serialize_goal(goal, state)
    links = (db.query(PlanObjective.id, PlanObjective.name)
             .join(GoalObjective, GoalObjective.objective_id == PlanObjective.id)
             .filter(GoalObjective.goal_id == goal.id).all())
    view["objectives"] = [{"id": str(i), "name": n} for i, n in links]
    return view


def goals_overview(db, user_id) -> dict:
    """Everything the Goals panel shows: proposals first, then the person's goals, and the active plan's objectives to
    link to. Proposes the active plan's goals once, if that has not happened yet."""
    propose_goals(db, user_id)
    uid = normalize_uuid(user_id)
    rows = (db.query(Goal).filter(Goal.user_id == uid, Goal.status != DROPPED)
            .order_by(Goal.priority.desc(), Goal.created_at.asc()).all())
    plan = _active_plan(db, user_id)
    views = [_view(db, g) for g in rows]
    return {
        "proposed": [v for v in views if v["status"] == PROPOSED],
        "goals": [v for v in views if v["status"] != PROPOSED],
        "objectives": _objectives(db, plan.id) if plan else [],
    }
