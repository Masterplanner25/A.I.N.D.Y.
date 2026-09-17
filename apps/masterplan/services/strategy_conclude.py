"""A strategy whose work is done is proposed for a verdict, not concluded for you.

`STRATEGY_LAYER_SPEC` §8 "Step 3b(v)": *"All of this strategy's tasks are done — conclude it?"
is the same shape as phase advance, one tier down.* Built 2026-09-16 as the third instance of the
repo's actuation shape (`phase_advance`, `pace`, and this): the system detects and proposes; the
human confirms or declines; a dismissal is recorded against the evidence it was built on and
lapses only when that evidence changes.

Two things distinguish this one from its siblings, and both are deliberate:

- **Confirming IS the existing verdict.** A strategy is *judged, never measured* (§6 Q5):
  `worked | did_not_work | inconclusive` is a human's call, so there is no `confirm` here that
  the system could make on the human's behalf. The proposal's confirm action is
  `POST /strategies/{id}/conclude {outcome}` (or `/abandon`), unchanged. This module only says
  *when to ask*.
- **The rule is binary, so there is nothing to calibrate.** Every task attached to the
  strategy is `completed`, and there is at least one. Unlike `pace`'s tolerance table, this
  needs no usage to be right; it can only be early (the strategy was under-tasked — the
  dismissal is for exactly that, as it was for phase advance's first live proposal).

A strategy with no tasks is never proposed: nothing was measured, so nothing is done. That is
also why *"the strategy's tasks changed"* is the only thing that brings a dismissed proposal
back — attaching the tasks that were missing is the review, arrived at from the other direction.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services.phase_advance import strategy_task_counts
from apps.masterplan.services.strategy_layer_service import serialize_strategy
from apps.masterplan.strategy_layer import STRATEGY_ACTIVE, PlanStrategy

logger = logging.getLogger(__name__)

REASON_WORK_COMPLETE = "work_complete"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _active_strategies(db: Session, masterplan_id: int) -> list[PlanStrategy]:
    return (
        db.query(PlanStrategy)
        .filter(
            PlanStrategy.masterplan_id == int(masterplan_id),
            PlanStrategy.status == STRATEGY_ACTIVE,
        )
        .order_by(PlanStrategy.created_at.asc())
        .all()
    )


def strategy_evidence(counts: dict[str, Any] | None) -> dict[str, Any]:
    """The numbers a verdict starts from. `work_complete` is the only trigger."""
    total = int((counts or {}).get("total") or 0)
    completed = int((counts or {}).get("completed") or 0)
    return {
        "tasks_total": total,
        "tasks_completed": completed,
        "hours_total": float((counts or {}).get("hours_total") or 0.0),
        "hours_completed": float((counts or {}).get("hours_completed") or 0.0),
        "work_complete": total >= 1 and completed == total,
    }


def _dismissal_stands(strategy: PlanStrategy, evidence: dict[str, Any]) -> bool:
    if strategy.conclude_dismissed_at is None:
        return False
    return int(strategy.conclude_dismissed_task_count or 0) == int(evidence["tasks_total"])


def _dismissed(strategy: PlanStrategy) -> dict[str, Any]:
    return {
        "at": _iso(strategy.conclude_dismissed_at),
        "task_count": strategy.conclude_dismissed_task_count,
    }


def propose_strategy_conclusions(
    db: Session, *, masterplan_id: int, user_id: Any
) -> dict[str, Any]:
    """Which active strategies have finished their work. Writes nothing.

    `proposed` lists the ones asking for a verdict; `dismissed` the ones the human already
    declined on this exact evidence (shown, not re-asked). Every entry carries the strategy and
    the numbers; a client keys on `strategy.id`.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        return {"proposed": [], "dismissed": [], "reason": "plan_not_found"}

    counts = strategy_task_counts(db, masterplan_id=plan.id, user_id=user_id or plan.user_id)
    proposed: list[dict[str, Any]] = []
    dismissed: list[dict[str, Any]] = []
    for strategy in _active_strategies(db, plan.id):
        evidence = strategy_evidence(counts.get(strategy.id))
        if not evidence["work_complete"]:
            continue
        entry = {
            "strategy": serialize_strategy(strategy),
            "reason": REASON_WORK_COMPLETE,
            "evidence": evidence,
        }
        if _dismissal_stands(strategy, evidence):
            entry["dismissed"] = _dismissed(strategy)
            dismissed.append(entry)
        else:
            proposed.append(entry)
    return {"proposed": proposed, "dismissed": dismissed}


def dismiss_strategy_conclusion(
    db: Session, *, masterplan_id: int, strategy_id: str, user_id: Any
) -> dict[str, Any]:
    """"Not done." Records the task count the proposal was built on; returns when it changes.

    Refuses when nothing is proposed for this strategy: there has to be something to decline.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        raise ValueError(f"MasterPlan {masterplan_id} not found")
    strategy = (
        db.query(PlanStrategy)
        .filter(PlanStrategy.id == str(strategy_id), PlanStrategy.masterplan_id == plan.id)
        .first()
    )
    if strategy is None:
        raise ValueError(f"strategy {strategy_id} is not on plan {masterplan_id}")
    if strategy.status != STRATEGY_ACTIVE:
        raise ValueError(f"strategy {strategy.name!r} is {strategy.status}, not active")

    counts = strategy_task_counts(db, masterplan_id=plan.id, user_id=user_id or plan.user_id)
    evidence = strategy_evidence(counts.get(strategy.id))
    if not evidence["work_complete"]:
        raise ValueError(
            f"nothing proposes concluding {strategy.name!r}; there is nothing to decline"
        )

    strategy.conclude_dismissed_at = _now()
    strategy.conclude_dismissed_task_count = int(evidence["tasks_total"])
    db.commit()
    db.refresh(strategy)
    return {
        "strategy": serialize_strategy(strategy),
        "dismissed": _dismissed(strategy),
        "returns_when": "the strategy's attached tasks change",
    }
