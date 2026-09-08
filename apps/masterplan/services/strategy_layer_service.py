"""Operating the strategy layer: propose, schedule, conclude, abandon, displace.

`STRATEGY_LAYER_SPEC.md` §5. Nothing here is read by the rest of the system yet — §8 requires
the six live phase-as-task rows to move first, and this is the shape they will move into.

★ **Three invariants carry the meaning of the layer**, and each is enforced here rather than
described:

1. **A displaced strategy has no outcome, ever.** It was never tried. Inventing a verdict for
   one is what would make a success rate computed over the set meaningless, and it is the exact
   collapse §5 says must not happen: *"we tried publishing and it did not move the objective"*
   and *"we never published because we did the partnership instead"* are different evidence.

2. **Abandoning does not cascade to completed tasks.** Incomplete ones return to the plan
   unattached; completed ones are untouched (§6 Q4). Cancelling them would destroy the record
   of work actually done and retroactively reduce WCU, which accrues from completed tasks —
   you did the work; the approach is what failed.

3. **Moving a strategy between phases is ordinary.** `phase_id` is scheduling, not ownership,
   so it changes freely; `objective_id` is ownership, and changing it changes what the strategy
   is for.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher
from AINDY.platform_layer.user_ids import parse_user_id
from apps.masterplan.strategy_layer import (
    ORIGIN_EMERGENT,
    ORIGIN_PLANNED,
    PHASE_PENDING,
    STRATEGY_ABANDONED,
    STRATEGY_ACTIVE,
    STRATEGY_CONCLUDED,
    STRATEGY_DISPLACED,
    STRATEGY_PROPOSED,
    VALID_PHASE_STATUSES,
    VALID_STRATEGY_ORIGINS,
    VALID_STRATEGY_OUTCOMES,
    PlanObjective,
    PlanPhase,
    PlanStrategy,
)

logger = logging.getLogger(__name__)

# Statuses that mean the strategy is over. `displaced` is here too — it is finished, it just
# finished without ever having been tried.
TERMINAL_STATUSES = {STRATEGY_CONCLUDED, STRATEGY_ABANDONED, STRATEGY_DISPLACED}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Objectives ────────────────────────────────────────────────────────────────────────

def create_objective(
    db: Session, *, user_id: Any, masterplan_id: int, name: str,
    intent: str | None = None, ordinal: int = 0,
) -> dict[str, Any]:
    cleaned = " ".join((name or "").split())[:300]
    if not cleaned:
        raise ValueError("an objective needs a name")
    row = PlanObjective(
        masterplan_id=int(masterplan_id),
        user_id=parse_user_id(user_id),
        name=cleaned,
        intent=intent,
        ordinal=int(ordinal),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_objective(row)


def serialize_objective(row: PlanObjective) -> dict[str, Any]:
    return {
        "id": row.id,
        "masterplan_id": row.masterplan_id,
        "name": row.name,
        "intent": row.intent or "",
        "ordinal": row.ordinal,
    }


def list_objectives(db: Session, *, masterplan_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(PlanObjective)
        .filter(PlanObjective.masterplan_id == int(masterplan_id))
        .order_by(PlanObjective.ordinal.asc(), PlanObjective.created_at.asc())
        .all()
    )
    return [serialize_objective(row) for row in rows]


# ── Phases ────────────────────────────────────────────────────────────────────────────

def create_phase(
    db: Session, *, user_id: Any, masterplan_id: int, name: str,
    description: str | None = None, ordinal: int = 0,
    duration_months: int | None = None, depends_on_phase_id: str | None = None,
) -> dict[str, Any]:
    cleaned = " ".join((name or "").split())[:300]
    if not cleaned:
        raise ValueError("a phase needs a name")
    row = PlanPhase(
        masterplan_id=int(masterplan_id),
        user_id=parse_user_id(user_id),
        name=cleaned,
        description=description,
        ordinal=int(ordinal),
        duration_months=duration_months,
        depends_on_phase_id=depends_on_phase_id,
        status=PHASE_PENDING,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_phase(row)


def serialize_phase(row: PlanPhase) -> dict[str, Any]:
    return {
        "id": row.id,
        "masterplan_id": row.masterplan_id,
        "name": row.name,
        "description": row.description or "",
        "ordinal": row.ordinal,
        "duration_months": row.duration_months,
        "status": row.status,
        # Carried explicitly, because the chain sets a sequential floor on the plan's ETA and
        # `ordinal` alone would not survive a reorder.
        "depends_on_phase_id": row.depends_on_phase_id,
    }


def list_phases(db: Session, *, masterplan_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(PlanPhase)
        .filter(PlanPhase.masterplan_id == int(masterplan_id))
        .order_by(PlanPhase.ordinal.asc(), PlanPhase.created_at.asc())
        .all()
    )
    return [serialize_phase(row) for row in rows]


def set_phase_status(db: Session, *, phase_id: str, status: str) -> dict[str, Any] | None:
    if status not in VALID_PHASE_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_PHASE_STATUSES)}")
    row = db.query(PlanPhase).filter(PlanPhase.id == str(phase_id)).first()
    if row is None:
        return None
    row.status = status
    if status == "active" and row.started_at is None:
        row.started_at = _now()
    if status == "complete":
        row.completed_at = _now()
    db.commit()
    db.refresh(row)
    return serialize_phase(row)


# ── Strategies ────────────────────────────────────────────────────────────────────────

def serialize_strategy(row: PlanStrategy) -> dict[str, Any]:
    return {
        "id": row.id,
        "masterplan_id": row.masterplan_id,
        "objective_id": row.objective_id,
        "phase_id": row.phase_id,
        "name": row.name,
        "description": row.description or "",
        "origin": row.origin,
        "status": row.status,
        "outcome": row.outcome,
        "outcome_note": row.outcome_note or "",
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "concluded_at": row.concluded_at.isoformat() if row.concluded_at else None,
    }


def create_strategy(
    db: Session, *, user_id: Any, masterplan_id: int, name: str,
    objective_id: str | None = None, phase_id: str | None = None,
    description: str | None = None, origin: str = ORIGIN_PLANNED,
) -> dict[str, Any]:
    """Propose a strategy, or record one that already happened.

    An `emergent` strategy with no `objective_id` is legal and is the most informative state
    the layer can hold: you did something the plan never anticipated. Today that leaves no
    trace anywhere, and it is what a *revise* is derived from (§5).
    """
    cleaned = " ".join((name or "").split())[:300]
    if not cleaned:
        raise ValueError("a strategy needs a name")
    if origin not in VALID_STRATEGY_ORIGINS:
        raise ValueError(f"origin must be one of {sorted(VALID_STRATEGY_ORIGINS)}")

    row = PlanStrategy(
        masterplan_id=int(masterplan_id),
        user_id=parse_user_id(user_id),
        objective_id=objective_id,
        phase_id=phase_id,
        name=cleaned,
        description=description,
        origin=origin,
        # An emergent strategy is being recorded after the fact, so "proposed" would be a lie
        # about its own history.
        status=STRATEGY_ACTIVE if origin == ORIGIN_EMERGENT else STRATEGY_PROPOSED,
        started_at=_now() if origin == ORIGIN_EMERGENT else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_strategy(row)


def start_strategy(db: Session, *, strategy_id: str) -> dict[str, Any] | None:
    row = _strategy(db, strategy_id)
    if row is None:
        return None
    if row.status in TERMINAL_STATUSES:
        raise ValueError(f"a {row.status} strategy cannot be started again")
    row.status = STRATEGY_ACTIVE
    if row.started_at is None:
        row.started_at = _now()
    db.commit()
    db.refresh(row)
    return serialize_strategy(row)


def move_strategy_to_phase(
    db: Session, *, strategy_id: str, phase_id: str | None
) -> dict[str, Any] | None:
    """Reschedule. Ordinary, and deliberately cheap.

    `phase_id` is scheduling, not ownership — which is the whole reason the owner's *"some
    things move phases"* is a refine rather than a plan rewrite.
    """
    row = _strategy(db, strategy_id)
    if row is None:
        return None
    row.phase_id = phase_id
    db.commit()
    db.refresh(row)
    return serialize_strategy(row)


def conclude_strategy(
    db: Session, *, strategy_id: str, outcome: str, note: str | None = None
) -> dict[str, Any] | None:
    """Judge how it went. Judged, never measured (§6 Q5)."""
    if outcome not in VALID_STRATEGY_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(VALID_STRATEGY_OUTCOMES)}")
    row = _strategy(db, strategy_id)
    if row is None:
        return None
    if row.status == STRATEGY_DISPLACED:
        # ★ Invariant 1. A displaced strategy was never tried, so there is nothing to judge.
        raise ValueError(
            "a displaced strategy has no outcome — it was never tried. "
            "Un-displace it first if it was actually attempted."
        )
    row.status = STRATEGY_CONCLUDED
    row.outcome = outcome
    row.outcome_note = note
    row.concluded_at = _now()
    db.commit()
    db.refresh(row)
    return serialize_strategy(row)


def abandon_strategy(
    db: Session, *, strategy_id: str, note: str | None = None, outcome: str | None = None
) -> dict[str, Any] | None:
    """Tried it; it did not work. A RESULT.

    ★ Invariant 2. Completed tasks are untouched; incomplete ones return to the plan
    unattached. Cascading to cancelled would destroy the record of work actually done — and it
    would contradict `masterplan_execution_service`, which already refuses to replace a plan's
    tasks when any are completed.
    """
    row = _strategy(db, strategy_id)
    if row is None:
        return None
    if outcome is not None and outcome not in VALID_STRATEGY_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(VALID_STRATEGY_OUTCOMES)}")

    row.status = STRATEGY_ABANDONED
    row.outcome = outcome or "did_not_work"
    row.outcome_note = note
    row.concluded_at = _now()
    released = _release_incomplete_tasks(db, row.id, row.user_id)
    db.commit()
    db.refresh(row)
    return serialize_strategy(row) | {"tasks_released": released}


def displace_strategy(
    db: Session, *, strategy_id: str, note: str | None = None
) -> dict[str, Any] | None:
    """Never tried; something else was done instead. A CHOICE.

    ★ Invariant 1 again, from the other side: no outcome is set, and any outcome already
    recorded is cleared. A displaced strategy that carried a verdict would be indistinguishable
    from one that failed, which is the collapse this layer exists to prevent.
    """
    row = _strategy(db, strategy_id)
    if row is None:
        return None
    row.status = STRATEGY_DISPLACED
    row.outcome = None
    row.outcome_note = note
    row.concluded_at = _now()
    released = _release_incomplete_tasks(db, row.id, row.user_id)
    db.commit()
    db.refresh(row)
    return serialize_strategy(row) | {"tasks_released": released}


def _release_incomplete_tasks(db: Session, strategy_id: str, user_id: Any) -> int:
    """Detach incomplete tasks; leave completed ones exactly as they are.

    The work happened. WCU accrues from completed tasks, so unlinking or cancelling them would
    retroactively reduce the work you did, which is false.

    Routed through `sys.v1.task.release_from_strategy` rather than importing `apps.tasks`:
    masterplan reaches tasks by syscall, pinned by
    `test_masterplan_bootstrap_keeps_only_identity_as_direct_app_dependency`, which is the same
    boundary its execution service already respects.

    Non-fatal. Concluding a strategy is a judgement someone made, and it must not fail because
    a task could not be detached — the strategy's own status is the record that matters, and a
    still-attached task is recoverable.
    """
    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id) if user_id else "",
        capabilities=["task.update"],
        trace_id="",
        metadata={"_db": db},
    )
    try:
        result = get_dispatcher().dispatch(
            "sys.v1.task.release_from_strategy", {"strategy_id": str(strategy_id)}, ctx
        )
    except Exception as exc:
        logger.warning("[strategy] task release failed for %s: %s", strategy_id, exc)
        return 0
    # Lowercase syscall envelope, not the uppercase flow one.
    if result.get("status") != "success":
        logger.warning(
            "[strategy] task release refused for %s: %s", strategy_id, result.get("error")
        )
        return 0
    return int((result.get("data") or {}).get("released") or 0)


def _strategy(db: Session, strategy_id: str) -> PlanStrategy | None:
    return db.query(PlanStrategy).filter(PlanStrategy.id == str(strategy_id)).first()


def list_strategies(
    db: Session, *, masterplan_id: int, objective_id: str | None = None,
    phase_id: str | None = None,
) -> list[dict[str, Any]]:
    query = db.query(PlanStrategy).filter(PlanStrategy.masterplan_id == int(masterplan_id))
    if objective_id is not None:
        query = query.filter(PlanStrategy.objective_id == objective_id)
    if phase_id is not None:
        query = query.filter(PlanStrategy.phase_id == phase_id)
    return [
        serialize_strategy(row)
        for row in query.order_by(PlanStrategy.created_at.asc()).all()
    ]


def unhoused_emergent_strategies(db: Session, *, masterplan_id: int) -> list[dict[str, Any]]:
    """Emergent strategies with no objective — the signal a *revise* is derived from.

    ★ §5's divergence table: an emergent strategy that succeeded and serves an existing
    objective is a **refine** (a route nobody wrote down). One that serves no objective is a
    **revise** — the plan is now aiming somewhere it does not say.
    """
    rows = (
        db.query(PlanStrategy)
        .filter(
            PlanStrategy.masterplan_id == int(masterplan_id),
            PlanStrategy.origin == ORIGIN_EMERGENT,
            PlanStrategy.objective_id.is_(None),
        )
        .order_by(PlanStrategy.created_at.asc())
        .all()
    )
    return [serialize_strategy(row) for row in rows]
