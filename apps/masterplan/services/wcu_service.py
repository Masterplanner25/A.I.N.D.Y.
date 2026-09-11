"""
WCU — Work Complexity Units (Masterplan physics).

``MasterPlan.total_wcu`` is the accumulated work-complexity of a plan's **completed** tasks —
the "workload currency" the phase-progression gate (``projection_service.evaluate_phase``)
checks against ``wcu_target``. It was declared in the schema but **never computed** (permanently
0), which left both ``total_wcu`` and the ``evaluate_phase`` gate inert. This service computes
and persists it, and re-evaluates the plan's phase — mirroring ``eta_service`` (same trigger
points, same plan-scoped read of the task dependency graph via the
``sys.v1.tasks.get_graph_context`` syscall, so there is no cross-app import).

WCU per completed task = ``effort_hours × complexity × difficulty``:
  * ``effort_hours`` — ``Task.duration`` (estimated hours) or ``WCU_DEFAULT_EFFORT_HOURS`` when
    the task carries no estimate (a completed task is still work).
  * ``complexity``   — ``Task.task_complexity`` (1-based).
  * ``difficulty``   — ``Task.task_difficulty`` (1-based).

Deterministic and tunable: larger / more complex / harder completed work earns more units.
Only *completed* tasks accrue WCU (it measures work done, not planned).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import require_user_id
from apps.masterplan.models import MasterPlan
from apps.masterplan.services.projection_service import evaluate_phase

logger = logging.getLogger(__name__)

# --- tunable WCU constants (deterministic; calibrate later, mirrors projection_service style) ---
WCU_DEFAULT_EFFORT_HOURS = 1.0   # completed task with no duration estimate → 1 base effort unit


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _graph_context(db: Session, user_id: str) -> dict:
    """Plan-scoped task graph via the same syscall the ETA service uses (no cross-app import)."""
    from apps.masterplan.services.eta_service import _graph_context as eta_graph_context

    return eta_graph_context(db, user_id)


def _task_wcu(node: dict) -> float:
    """WCU earned by a single completed task node = effort_hours × complexity × difficulty."""
    duration = float(node.get("duration") or 0.0)
    effort_hours = duration if duration > 0 else WCU_DEFAULT_EFFORT_HOURS
    complexity = max(1, int(node.get("task_complexity") or 1))
    difficulty = max(1, int(node.get("task_difficulty") or 1))
    return effort_hours * complexity * difficulty


def compute_total_wcu(graph: dict, plan_id: Any) -> tuple[float, int]:
    """Sum WCU over the plan's completed tasks. Returns ``(total_wcu, completed_count)``.

    Pure function over a ``get_graph_context`` result — easy to unit-test in isolation.
    """
    plan_id_int = _as_int(plan_id)
    if plan_id_int is None:
        return 0.0, 0
    nodes = (graph or {}).get("nodes") or {}
    total = 0.0
    completed = 0
    for node in nodes.values():
        if _as_int(node.get("masterplan_id")) != plan_id_int:
            continue
        if str(node.get("status") or "") != "completed":
            continue
        total += _task_wcu(node)
        completed += 1
    return round(total, 2), completed


def calculate_wcu(db: Session, masterplan_id: int, user_id: str) -> dict:
    """Compute + persist ``total_wcu`` for one plan, then re-evaluate its phase.

    Mirrors ``eta_service.calculate_eta``: plan-scoped, reads the task graph via syscall,
    persists to the plan, commits. Re-runs ``evaluate_phase`` (which was previously never
    called) so phase progression reflects the freshly-computed WCU alongside the other
    threshold fields. Phase evaluation is defensive — a failure there never blocks the WCU write.
    """
    owner_user_id = require_user_id(user_id)
    plan = (
        db.query(MasterPlan)
        .filter(MasterPlan.id == masterplan_id, MasterPlan.user_id == owner_user_id)
        .first()
    )
    if not plan:
        raise ValueError(f"MasterPlan {masterplan_id} not found for user {user_id}")

    total_wcu, completed = compute_total_wcu(_graph_context(db, owner_user_id), plan.id)
    plan.total_wcu = total_wcu

    prior_phase = plan.phase
    try:
        # ★ A plan with a strategy layer is not flipped by a threshold. Its phase is whatever
        # `plan_phases` says, and it moves only when the human confirms a proposal
        # (`phase_advance.confirm_phase_advance`, STRATEGY_LAYER_SPEC §6 Q8). The threshold
        # gate stays for plans that predate the layer, where it is the only reading there is.
        layer_phase = _phase_from_layer(db, plan.id)
        plan.phase = layer_phase if layer_phase is not None else evaluate_phase(plan)
    except Exception as exc:  # pragma: no cover - defensive; WCU write must not break on phase
        logger.warning("[WCU] evaluate_phase failed for plan %s (WCU still persisted): %s", plan.id, exc)

    db.commit()

    return {
        "masterplan_id": plan.id,
        "total_wcu": total_wcu,
        "wcu_target": float(plan.wcu_target or 0.0),
        "completed_tasks": completed,
        "phase": plan.phase,
        "phase_advanced": bool(plan.phase != prior_phase),
    }


def _phase_from_layer(db: Session, masterplan_id: int) -> int | None:
    """The legacy integer read off `plan_phases`; `None` when the plan has no layer."""
    from apps.masterplan.services.phase_advance import derive_legacy_phase
    from apps.masterplan.strategy_layer import PlanPhase

    phases = (
        db.query(PlanPhase)
        .filter(PlanPhase.masterplan_id == int(masterplan_id))
        .order_by(PlanPhase.ordinal.asc(), PlanPhase.created_at.asc())
        .all()
    )
    if not phases:
        return None
    return derive_legacy_phase(phases)


def recalculate_all_wcu(db: Session) -> int:
    """Recompute WCU for every active plan (scheduler path). Mirrors ``recalculate_all_etas``."""
    plans = db.query(MasterPlan).filter(MasterPlan.is_active.is_(True)).all()
    updated = 0
    for plan in plans:
        try:
            calculate_wcu(db, plan.id, str(plan.user_id))
            updated += 1
        except Exception as exc:  # pragma: no cover - one bad plan must not stop the sweep
            logger.warning("[WCU] recalc failed for plan %s: %s", plan.id, exc)
    return updated
