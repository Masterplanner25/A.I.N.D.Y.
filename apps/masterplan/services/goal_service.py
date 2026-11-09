from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import logging

from AINDY.core.system_event_types import SystemEventTypes
from AINDY.platform_layer.registry import emit_event
from apps.masterplan.models import GoalState
from apps.masterplan.models import Goal, GoalObjective
from AINDY.utils.uuid_utils import normalize_uuid

logger = logging.getLogger(__name__)

# GOALS_LAYER_SPEC §4 (decided 2026-11-09): a goal's progress follows from how it is measured.
MEASURE_ANCHOR = "anchor"          # a number, a unit and a date: resolved like the plan's anchor
MEASURE_OBJECTIVES = "objectives"  # the attainment of the linked plan objectives
MEASURE_DECLARED = "declared"      # qualitative: no progress number; the person marks it done (decision 2)
MEASURES = (MEASURE_ANCHOR, MEASURE_OBJECTIVES, MEASURE_DECLARED)
SOURCES = ("anchor", "success_criterion", "stated")
# A declared goal has no progress, so ranking reads its gap as neither done nor untouched.
UNMEASURED_GAP = 0.5


def create_goal(
    db,
    *,
    user_id: str,
    name: str,
    description: str | None = None,
    goal_type: str = "strategic",
    priority: float = 0.5,
    status: str = "active",
    success_metric: dict[str, Any] | None = None,
    source: str = "stated",
    measure: str = MEASURE_DECLARED,
    masterplan_id: int | None = None,
    target_value: float | None = None,
    unit: str | None = None,
    target_date: datetime | None = None,
    objective_ids: list[str] | None = None,
) -> dict[str, Any]:
    measure = str(measure or MEASURE_DECLARED).strip().lower()
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of: {', '.join(MEASURES)}")
    source = str(source or "stated").strip().lower()
    if source not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(SOURCES)}")
    goal = Goal(
        user_id=normalize_uuid(user_id),
        name=str(name).strip(),
        description=description,
        goal_type=str(goal_type or "strategic").strip().lower(),
        priority=float(priority or 0.5),
        status=str(status or "active").strip().lower(),
        success_metric=success_metric or {},
        source=source,
        measure=measure,
        masterplan_id=masterplan_id,
        target_value=target_value,
        unit=unit,
        target_date=target_date,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(goal)
    db.flush()
    for objective_id in dict.fromkeys(objective_ids or []):
        db.add(GoalObjective(goal_id=goal.id, objective_id=str(objective_id)))
    db.commit()
    db.refresh(goal)
    state = _get_or_create_goal_state(db, goal.id)
    _apply_measure(db, goal, state)
    db.commit()
    db.refresh(goal)
    db.refresh(state)
    return _serialize_goal(goal, state)


def measure_goal(db, goal: Goal) -> dict[str, Any]:
    """A goal's progress by its measure (GOALS_LAYER_SPEC §4): ``{"progress": 0..1 | None, "reason": str | None}``.

    ``None`` is never 0: an anchor whose unit nothing measures, or objectives with no planned work, are *unmeasured*,
    and a declared goal has no number by design. Nothing is manufactured (audit D4)."""
    measure = goal.measure or MEASURE_DECLARED
    if measure == MEASURE_ANCHOR:
        from AINDY.platform_layer.registry import get_job

        resolve = get_job("analytics.resolve_goal_attainment")
        if resolve is None:
            return {"progress": None, "reason": "no_resolver"}
        result = resolve(db, user_id=str(goal.user_id), goal_unit=goal.unit, goal_value=goal.target_value,
                         masterplan_id=goal.masterplan_id) or {}
        if not result.get("supported") or result.get("attainment_pct") is None:
            return {"progress": None, "reason": result.get("reason") or "unmeasured"}
        # A value of 0 means nothing has been recorded toward it (live 2026-11-09: USD read 0.000, since freelance
        # revenue has never held a row). That is "no measurement yet", never 0% (§4, audit D4).
        if float(result.get("value") or 0.0) <= 0.0:
            return {"progress": None, "reason": "nothing_recorded_yet"}
        return {"progress": round(float(result["attainment_pct"]), 4), "reason": None}
    if measure == MEASURE_OBJECTIVES:
        from apps.masterplan.services.phase_advance import objective_attainment
        from apps.masterplan.strategy_layer import PlanObjective

        linked = (db.query(PlanObjective.id, PlanObjective.masterplan_id)
                  .join(GoalObjective, GoalObjective.objective_id == PlanObjective.id)
                  .filter(GoalObjective.goal_id == goal.id).all())
        if not linked:
            return {"progress": None, "reason": "no_linked_objectives"}
        wanted = {str(oid) for oid, _ in linked}
        values: list[float] = []
        for plan_id in {pid for _, pid in linked}:
            reading = objective_attainment(db, masterplan_id=plan_id, user_id=goal.user_id)
            values += [float(o["attainment_pct"]) for o in reading.get("objectives") or []
                       if str(o.get("id")) in wanted and o.get("attainment_pct") is not None]
        if not values:
            return {"progress": None, "reason": "no_work_planned"}
        return {"progress": round(sum(values) / len(values), 4), "reason": None}
    return {"progress": None, "reason": "declared"}


def _apply_measure(db, goal: Goal, state: GoalState) -> bool:
    """Store the measured progress on the goal's state. Only an ANCHOR goal completes by itself, at 0.999 or more.
    Returns whether the status changed.

    Owner, 2026-11-09: an objectives goal never completes by itself. Its percentage is planned work done out of planned
    work, so one finished task under an objective read 100% and "Formation of strategic partnerships" completed itself
    the moment it was confirmed. At 100% it reads "all planned work done", and the person marks it done, as with a
    declared goal (decision 2)."""
    reading = measure_goal(db, goal)
    state.progress = reading["progress"]
    state.last_update = datetime.now(timezone.utc)
    if (goal.measure == MEASURE_ANCHOR and reading["progress"] is not None and reading["progress"] >= 0.999
            and goal.status == "active"):
        goal.status = "completed"
        goal.updated_at = datetime.now(timezone.utc)
        return True
    return False


def refresh_goal_states(db, user_id: str | None) -> list[dict[str, Any]]:
    """Recompute every active goal's progress from its measure. This replaced the keyword-overlap nudge on each
    execution (decision 3, retired 2026-11-09)."""
    if not user_id:
        return []
    goals = (db.query(Goal).filter(Goal.user_id == normalize_uuid(user_id), Goal.status == "active").all())
    if not goals:
        return []
    changed = []
    for goal in goals:
        state = _get_or_create_goal_state(db, goal.id)
        if _apply_measure(db, goal, state):
            changed.append(goal)
    db.commit()
    for goal in changed:
        emit_event(
            SystemEventTypes.MASTERPLAN_GOAL_STATE_CHANGED,
            {"user_id": str(goal.user_id), "goal_id": str(goal.id), "status": str(goal.status),
             "updated_at": goal.updated_at.isoformat() if goal.updated_at else datetime.now(timezone.utc).isoformat()},
        )
    return get_active_goals(db, user_id)


def get_active_goals(db, user_id: str | None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    rows = (
        db.query(Goal, GoalState)
        .outerjoin(GoalState, GoalState.goal_id == Goal.id)
        .filter(Goal.user_id == normalize_uuid(user_id), Goal.status == "active")
        .order_by(Goal.priority.desc(), Goal.updated_at.desc())
        .all()
    )
    return [_serialize_goal(goal, state) for goal, state in rows]


def rank_goals(
    db,
    user_id: str | None,
    *,
    system_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    goals = get_active_goals(db, user_id)
    if not goals:
        return []

    state = system_state or {}
    health_status = str(state.get("health_status") or "healthy").lower()
    system_load = float(state.get("system_load") or 0.0)
    failure_rate = float(state.get("failure_rate") or 0.0)

    ranked = []
    for goal in goals:
        progress = goal.get("progress")
        progress_gap = UNMEASURED_GAP if progress is None else max(0.0, 1.0 - float(progress))
        success_signal = float(goal.get("success_signal") or 0.0)
        base_priority = float(goal.get("priority") or 0.0)
        score = base_priority * 0.45 + progress_gap * 0.30 + max(0.0, success_signal) * 0.15
        if health_status == "critical" and goal.get("goal_type") == "operational":
            score -= 0.10
        if system_load >= 0.75 and goal.get("goal_type") == "learning":
            score -= 0.05
        if failure_rate >= 0.25:
            score -= min(0.10, abs(min(0.0, success_signal)) * 0.10)
        enriched = dict(goal)
        enriched["ranked_priority"] = round(max(0.0, min(1.5, score)), 4)
        enriched["progress_gap"] = round(progress_gap, 4)
        ranked.append(enriched)

    ranked.sort(key=lambda item: item["ranked_priority"], reverse=True)
    return ranked


def update_goal_progress(db, goal_id: str, result: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any] | None:
    q = db.query(Goal).filter(Goal.id == goal_id)
    if user_id is not None:
        q = q.filter(Goal.user_id == normalize_uuid(user_id))
    goal = q.first()
    if not goal:
        return None
    state = _get_or_create_goal_state(db, goal.id)

    progress_delta = float(result.get("progress_delta") or 0.0)
    success_delta = float(result.get("success_signal_delta") or 0.0)
    action = result.get("action")
    previous_status = str(goal.status or "active")

    state.progress = round(max(0.0, min(1.0, float(state.progress or 0.0) + progress_delta)), 4)
    state.success_signal = round(max(-1.0, min(1.0, float(state.success_signal or 0.0) + success_delta)), 4)
    state.last_update = datetime.now(timezone.utc)
    actions = list(state.recent_actions or [])
    if action:
        actions.append(action)
    state.recent_actions = actions[-10:]
    goal.updated_at = datetime.now(timezone.utc)
    if state.progress >= 0.999:
        goal.status = "completed"
    db.commit()
    db.refresh(state)
    db.refresh(goal)
    if str(goal.status or previous_status) != previous_status:
        emit_event(
            SystemEventTypes.MASTERPLAN_GOAL_STATE_CHANGED,
            {
                "user_id": str(goal.user_id),
                "goal_id": str(goal.id),
                "status": str(goal.status),
                "updated_at": goal.updated_at.isoformat() if goal.updated_at else datetime.now(timezone.utc).isoformat(),
            },
        )
    return _serialize_goal(goal, state)


def detect_goal_drift(db, user_id: str | None) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    for goal in get_active_goals(db, user_id):
        success_signal = float(goal.get("success_signal") or 0.0)
        progress = goal.get("progress")
        low = progress is not None and float(progress) < 0.15  # a declared goal has no progress to be low
        if success_signal < -0.35 or (low and len(goal.get("recent_actions") or []) >= 5):
            drift.append(
                {
                    "goal_id": goal["id"],
                    "name": goal["name"],
                    "reason": "repeated_failures" if success_signal < -0.35 else "low_progress",
                    "progress": progress,
                    "success_signal": success_signal,
                }
            )
    return drift


def calculate_goal_alignment(goals: list[dict[str, Any]], text: str | None) -> float:
    if not goals or not text:
        return 0.0
    action_terms = set(_extract_terms(text))
    if not action_terms:
        return 0.0

    best = 0.0
    for goal in goals:
        goal_terms = set(_extract_terms(" ".join(filter(None, [goal.get("name"), goal.get("description")]))))
        if not goal_terms:
            continue
        overlap = len(action_terms & goal_terms)
        if overlap == 0:
            continue
        coverage = overlap / max(1, len(goal_terms))
        weighted = coverage * float(goal.get("ranked_priority") or goal.get("priority") or 0.0)
        best = max(best, weighted)
    return round(min(1.0, best), 4)


def update_goals_from_execution(
    db,
    *,
    user_id: str | None,
    workflow_type: str | None = None,
    execution_result: Any = None,
    success: bool = True,
) -> list[dict[str, Any]]:
    """After an execution: recompute the person's goals from their measures (GOALS_LAYER_SPEC §4).

    Until 2026-11-09 this nudged the top 5 goals' progress by keyword overlap between the run's text and each goal's
    name, the measure the strategy layer had deliberately not repeated. The owner retired it (decision 3): progress now
    moves only when the anchor's value or the linked objectives' attributed work moves. The run's arguments are kept
    for the callers' sake and no longer read."""
    return refresh_goal_states(db, user_id)


def get_goal_states(db, user_id: str | None) -> list[dict[str, Any]]:
    return rank_goals(db, user_id)


def handle_score_updated(payload: dict) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        return
    logger.debug(
        "[Masterplan] observed analytics score update for user=%s score=%s",
        user_id,
        payload.get("score"),
    )


def distribute_goals(
    db,
    goals: list[dict[str, Any]],
    *,
    agent_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from AINDY.agents.agent_coordinator import list_agents

    candidates = agent_candidates or list_agents(db)
    assignments: list[dict[str, Any]] = []
    ranked_candidates = list(candidates)
    for goal in goals:
        ranked_candidates.sort(key=lambda item: (item.get("load", 1.0), item.get("health_status") != "healthy"))
        if not ranked_candidates:
            break
        best = ranked_candidates[0]
        assignments.append(
            {
                "goal_id": goal.get("id"),
                "goal_name": goal.get("name"),
                "agent_id": best.get("agent_id"),
                "goal_type": goal.get("goal_type"),
                "priority": goal.get("ranked_priority") or goal.get("priority"),
            }
        )
    return assignments


def _get_or_create_goal_state(db, goal_id) -> GoalState:
    state = db.query(GoalState).filter(GoalState.goal_id == goal_id).first()
    if state:
        return state
    state = GoalState(goal_id=goal_id, progress=None, recent_actions=[], success_signal=0.0)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def _serialize_goal(goal: Goal, state: GoalState | None) -> dict[str, Any]:
    return {
        "id": str(goal.id),
        "user_id": str(goal.user_id),
        "name": goal.name,
        "description": goal.description,
        "goal_type": goal.goal_type,
        "priority": float(goal.priority or 0.0),
        "status": goal.status,
        "success_metric": goal.success_metric or {},
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
        # None for a declared or unmeasured goal; never shown as 0 (GOALS_LAYER_SPEC §4).
        "progress": None if state is None or state.progress is None else float(state.progress),
        "source": goal.source,
        "measure": goal.measure or MEASURE_DECLARED,
        # Decision 4: only a goal with a measure AND a reading may override the loop's next action.
        "measured": (goal.measure in (MEASURE_ANCHOR, MEASURE_OBJECTIVES)
                     and state is not None and state.progress is not None),
        "masterplan_id": goal.masterplan_id,
        "target_value": goal.target_value,
        "unit": goal.unit,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "last_update": state.last_update.isoformat() if state and state.last_update else None,
        "recent_actions": list(getattr(state, "recent_actions", []) or []),
        "success_signal": float(getattr(state, "success_signal", 0.0) or 0.0),
    }


def _extract_terms(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        term
        for term in str(text).lower().replace(".", " ").replace("_", " ").replace("-", " ").split()
        if len(term) > 2
    ]
