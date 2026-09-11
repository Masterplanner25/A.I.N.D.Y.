"""Phase advance is a proposal the human confirms, not a status the system flips.

`STRATEGY_LAYER_SPEC` §6 Q8 and §8 step 3b. The owner, 2026-09-05:

> *"A bit of both really. A phase being completed should trigger something like a review/refine
> of the plan — especially if you finish some things quicker than you thought. Maybe some things
> move phases, maybe some things get done at the same time."*

So the split is: **the system detects and proposes; the human confirms; the confirmation opens a
review rather than merely closing a row.** Phase completion is an event that starts a
conversation, and the point where that conversation is most valuable — early completion — is
exactly the point the old gate could not see.

★ What this replaces. `projection_service.evaluate_phase` returned `1` or `2` for a five-phase
plan, gated on threshold columns nobody chose (books, a studio, playbooks), and `wcu_service`
wrote its answer straight onto `plan.phase` on every recalculation. Two things were wrong with
that at once: it flipped without asking, and it measured against requirements the plan never
declared. Here the evidence is the plan's own phases — the work attached to one, and the window
it was given — and the answer is a proposal.

Two kinds of evidence, in order of how much they mean:

- **`work_complete`** — every task attached to the phase is done, and there is at least one.
  This is the trigger the owner described, and when it lands before the phase's window ends the
  proposal says by how much. That number is the review's opening line.
- **`window_elapsed`** — the phase's scheduled window has passed. Weaker: the calendar ran out,
  which says nothing about the work. It still deserves a look, because a phase that overran is
  the other thing a review is for.

Nothing here reads `evaluate_phase`'s threshold columns, and nothing writes `plan.phase` except
`confirm_phase_advance`, which derives it from the layer so the legacy integer keeps meaning
"which phase we are in" for whatever still reads it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher
from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services.strategy_layer_service import serialize_phase
from apps.masterplan.strategy_layer import PHASE_ACTIVE, PHASE_COMPLETE, PHASE_PENDING, PlanPhase

logger = logging.getLogger(__name__)

REASON_WORK_COMPLETE = "work_complete"
REASON_WINDOW_ELAPSED = "window_elapsed"

# `duration_months` is what Genesis wrote and what the seeder carried. A calendar month has no
# fixed length; this is the mean Gregorian month, and the window it produces is a planning
# horizon, not a deadline — a day either way changes nothing that matters.
_DAYS_PER_MONTH = 30.4375

TASK_COMPLETE = "completed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    """`MasterPlan.start_date` is a naive column; the phase timestamps are aware. Fold the
    naive one to UTC rather than let the comparison raise — the same trap `projection_service`
    documents, and the same fix."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# ── where the plan is ─────────────────────────────────────────────────────────────────

def _phases(db: Session, masterplan_id: int) -> list[PlanPhase]:
    return (
        db.query(PlanPhase)
        .filter(PlanPhase.masterplan_id == int(masterplan_id))
        .order_by(PlanPhase.ordinal.asc(), PlanPhase.created_at.asc())
        .all()
    )


def frontier_phase(phases: list[PlanPhase]) -> PlanPhase | None:
    """The phase the plan is in: the active one, else the first pending one whose
    dependency is satisfied. `None` when every phase is complete.

    Walks the edge, not the ordinal — `depends_on_phase_id` is what carries the order
    (`STRATEGY_LAYER_SPEC` §8), and `ordinal` is a display concern.
    """
    for row in phases:
        if row.status == PHASE_ACTIVE:
            return row
    complete = {row.id for row in phases if row.status == PHASE_COMPLETE}
    for row in phases:
        if row.status == PHASE_COMPLETE:
            continue
        if row.depends_on_phase_id is None or row.depends_on_phase_id in complete:
            return row
    return None


def _successor(phases: list[PlanPhase], phase: PlanPhase) -> PlanPhase | None:
    """The phase that depends on this one; failing an edge, the next by ordinal."""
    for row in phases:
        if row.depends_on_phase_id == phase.id:
            return row
    later = [row for row in phases if row.ordinal > phase.ordinal and row.status != PHASE_COMPLETE]
    return later[0] if later else None


def phase_window(
    plan: MasterPlan, phases: list[PlanPhase], phase: PlanPhase
) -> tuple[datetime | None, datetime | None]:
    """The window the plan gave this phase: `start_date` plus every earlier phase's duration,
    to that plus its own. `None` at either end when a duration is missing — a phase with no
    length has no schedule to be early or late against."""
    start = _as_aware(plan.start_date)
    if start is None:
        return None, None
    for row in phases:
        if row.ordinal >= phase.ordinal:
            break
        if row.duration_months is None:
            return None, None
        start = start + timedelta(days=row.duration_months * _DAYS_PER_MONTH)
    if phase.duration_months is None:
        return start, None
    return start, start + timedelta(days=phase.duration_months * _DAYS_PER_MONTH)


# ── the evidence ──────────────────────────────────────────────────────────────────────

def _tasks_for(db: Session, *, masterplan_id: int, user_id: Any) -> list[dict[str, Any]]:
    """Through the task syscall, not an import: masterplan reaches tasks by syscall
    (`test_masterplan_bootstrap_keeps_only_identity_as_direct_app_dependency`)."""
    return _dispatch_tasks(
        db, "sys.v1.task.list_for_masterplan",
        {"masterplan_id": int(masterplan_id)}, user_id=user_id,
    ).get("tasks") or []


def _dispatch_tasks(db: Session, name: str, payload: dict, *, user_id: Any) -> dict[str, Any]:
    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id) if user_id else "",
        capabilities=["task.read", "task.update"],
        trace_id="",
        metadata={"_db": db},
    )
    try:
        result = get_dispatcher().dispatch(name, payload, ctx)
    except Exception as exc:
        logger.warning("[phase-advance] %s failed: %s", name, exc)
        return {}
    # Lowercase syscall envelope, not the uppercase flow one.
    if result.get("status") != "success":
        logger.warning("[phase-advance] %s refused: %s", name, result.get("error"))
        return {}
    return result.get("data") or {}


def _evidence(
    plan: MasterPlan, phases: list[PlanPhase], phase: PlanPhase, tasks: list[dict[str, Any]],
    *, now: datetime,
) -> dict[str, Any]:
    attached = [t for t in tasks if str(t.get("phase_id") or "") == phase.id]
    completed = [t for t in attached if str(t.get("status") or "") == TASK_COMPLETE]
    open_tasks = [t for t in attached if t not in completed]
    start, end = phase_window(plan, phases, phase)

    work_complete = bool(attached) and not open_tasks
    window_elapsed = end is not None and now >= end
    early_by_days = None
    if work_complete and end is not None and now < end:
        early_by_days = (end - now).days

    return {
        "tasks_total": len(attached),
        "tasks_completed": len(completed),
        "open_task_ids": [int(t["id"]) for t in open_tasks if t.get("id") is not None],
        "window_start": _iso(start),
        "window_end": _iso(end),
        "work_complete": work_complete,
        "window_elapsed": window_elapsed,
        "early_by_days": early_by_days,
    }


# ── propose ───────────────────────────────────────────────────────────────────────────

def propose_phase_advance(
    db: Session, *, masterplan_id: int, user_id: Any, now: datetime | None = None
) -> dict[str, Any]:
    """What the system has to say about the plan's current phase. Writes nothing.

    `proposed` is the only key a caller has to read. When it is true, `reason` says which
    evidence produced it and `evidence` carries the numbers the review starts from — most
    usefully `early_by_days`, which is the case the owner named.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        return {"proposed": False, "reason": "plan_not_found"}
    phases = _phases(db, plan.id)
    if not phases:
        return {"proposed": False, "reason": "no_phases"}
    phase = frontier_phase(phases)
    if phase is None:
        return {"proposed": False, "reason": "all_phases_complete"}

    moment = now or _now()
    tasks = _tasks_for(db, masterplan_id=plan.id, user_id=user_id or plan.user_id)
    evidence = _evidence(plan, phases, phase, tasks, now=moment)
    successor = _successor(phases, phase)

    payload = {
        "proposed": False,
        "phase": serialize_phase(phase),
        "next_phase": serialize_phase(successor) if successor is not None else None,
        "evidence": evidence,
        "dismissed": None,
    }
    if evidence["work_complete"]:
        payload["reason"] = REASON_WORK_COMPLETE
    elif evidence["window_elapsed"]:
        payload["reason"] = REASON_WINDOW_ELAPSED
    else:
        return payload

    # ★ The human already said "not done", and nothing about the phase's work has changed
    # since. Re-proposing on the same evidence is nagging, not proposing. The moment a task is
    # attached or removed the count differs, the dismissal lapses, and the question is asked
    # again — because it is now a different question.
    if _dismissal_stands(phase, evidence):
        payload["dismissed"] = {
            "at": _iso(phase.advance_dismissed_at),
            "task_count": phase.advance_dismissed_task_count,
        }
        return payload

    payload["proposed"] = True
    return payload


def _dismissal_stands(phase: PlanPhase, evidence: dict[str, Any]) -> bool:
    if phase.advance_dismissed_at is None:
        return False
    return int(phase.advance_dismissed_task_count or 0) == int(evidence["tasks_total"])


# ── decline ───────────────────────────────────────────────────────────────────────────────────────

def dismiss_phase_advance(
    db: Session, *, masterplan_id: int, phase_id: str, user_id: Any
) -> dict[str, Any]:
    """The human's other half: "not done". A proposal that can only be accepted is not one.

    The first live proposal drew exactly this — *"what if the phase isn't complete?"* — and
    the honest reading of *Foundation Building, 2 of 2 tasks, 360 days early* was
    under-tasked, not finished. Dismissing records the evidence the proposal was built on, so
    it comes back when the work changes and not before. What "the work changes" usually means
    in practice is attaching the tasks that were missing, which is the review the owner
    asked for, arrived at from the other direction.

    Refuses when nothing is proposed: there has to be something to decline.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        raise ValueError(f"MasterPlan {masterplan_id} not found")
    phases = _phases(db, plan.id)
    phase = next((row for row in phases if row.id == str(phase_id)), None)
    if phase is None:
        raise ValueError(f"phase {phase_id} is not on plan {masterplan_id}")
    frontier = frontier_phase(phases)
    if frontier is None or frontier.id != phase.id:
        raise ValueError(f"phase {phase.name!r} is not the plan's current phase")

    tasks = _tasks_for(db, masterplan_id=plan.id, user_id=user_id or plan.user_id)
    evidence = _evidence(plan, phases, phase, tasks, now=_now())
    if not (evidence["work_complete"] or evidence["window_elapsed"]):
        raise ValueError(f"nothing proposes closing {phase.name!r}; there is nothing to decline")

    phase.advance_dismissed_at = _now()
    phase.advance_dismissed_task_count = int(evidence["tasks_total"])
    db.commit()
    db.refresh(phase)
    return {
        "phase": serialize_phase(phase),
        "dismissed": {
            "at": _iso(phase.advance_dismissed_at),
            "task_count": phase.advance_dismissed_task_count,
        },
        # The proposal returns when this number changes.
        "returns_when": "the phase's attached tasks change",
    }


# ── reopen ───────────────────────────────────────────────────────────────────────────────────────

def reopen_phase(
    db: Session, *, masterplan_id: int, phase_id: str, user_id: Any
) -> dict[str, Any]:
    """Reverse a confirmation. The phase becomes the frontier again; its successor steps back.

    Only the most recently closed phase can reopen — the one whose successor is the current
    frontier — for the same reason `confirm` only closes the frontier: the chain is the plan's
    sequential floor, and a hole in the middle of it is not a state the plan can be in.

    Tasks are left where they are. The confirmation may have moved open work forward, and
    moving it back would guess that the human wants the old scheduling rather than the phase;
    the ids that moved were returned at confirmation time and a task can be moved again.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        raise ValueError(f"MasterPlan {masterplan_id} not found")
    phases = _phases(db, plan.id)
    phase = next((row for row in phases if row.id == str(phase_id)), None)
    if phase is None:
        raise ValueError(f"phase {phase_id} is not on plan {masterplan_id}")
    if phase.status != PHASE_COMPLETE:
        raise ValueError(f"phase {phase.name!r} is not complete; there is nothing to reopen")

    successor = _successor(phases, phase)
    frontier = frontier_phase(phases)
    # Last phase closed: no successor, and the frontier is None because everything is complete.
    # Otherwise the successor must be the frontier, i.e. nothing after this phase has closed.
    if successor is not None and (frontier is None or frontier.id != successor.id):
        later = frontier.name if frontier is not None else "the later phases"
        raise ValueError(
            f"phase {phase.name!r} is not the most recently closed phase; reopen {later!r} first"
        )

    phase.status = PHASE_ACTIVE
    phase.completed_at = None
    # A reopened phase is a fresh question; the old "not done" no longer applies to it.
    phase.advance_dismissed_at = None
    phase.advance_dismissed_task_count = None
    if successor is not None and successor.status == PHASE_ACTIVE:
        successor.status = PHASE_PENDING
        successor.started_at = None
    plan.phase = derive_legacy_phase(phases)
    db.commit()
    for row in (phase, successor):
        if row is not None:
            db.refresh(row)
    return {
        "reopened": serialize_phase(phase),
        "stepped_back": serialize_phase(successor) if successor is not None else None,
        "plan_phase": plan.phase,
    }


# ── confirm ───────────────────────────────────────────────────────────────────────────

def confirm_phase_advance(
    db: Session, *, masterplan_id: int, phase_id: str, user_id: Any
) -> dict[str, Any]:
    """The human's half. Closes the phase, opens the next, and hands back what the review
    should look at.

    Refuses to close anything but the frontier: the chain is the plan's sequential floor
    (`eta_service._phase_chain_depth`), and closing a phase out of order would punch a hole
    in it. Refuses without evidence too — confirming is agreeing with a proposal, and there
    has to be one. The route is the place to relax that if a plain "close it" is ever wanted.

    ★ Open work in the closed phase moves to the next one. This is the mechanical half of
    *"maybe some things move phases"*: a closed phase cannot hold open work, the next phase is
    the only defensible destination, and a task can be moved again. The moved ids are returned
    so the review can start with them — they are the things that did not happen when the plan
    said they would.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        raise ValueError(f"MasterPlan {masterplan_id} not found")
    phases = _phases(db, plan.id)
    phase = next((row for row in phases if row.id == str(phase_id)), None)
    if phase is None:
        raise ValueError(f"phase {phase_id} is not on plan {masterplan_id}")
    frontier = frontier_phase(phases)
    if frontier is None:
        raise ValueError(f"phase {phase.name!r} cannot close: every phase is already complete")
    if frontier.id != phase.id:
        raise ValueError(
            f"phase {phase.name!r} is not the plan's current phase; {frontier.name!r} is"
        )

    owner = user_id or plan.user_id
    tasks = _tasks_for(db, masterplan_id=plan.id, user_id=owner)
    evidence = _evidence(plan, phases, phase, tasks, now=_now())
    if not (evidence["work_complete"] or evidence["window_elapsed"]):
        raise ValueError(
            f"nothing proposes closing {phase.name!r}: "
            f"{evidence['tasks_completed']} of {evidence['tasks_total']} tasks complete "
            f"and the window has not ended"
        )

    successor = _successor(phases, phase)
    moment = _now()
    phase.status = PHASE_COMPLETE
    phase.completed_at = moment
    moved = 0
    if successor is not None:
        successor.status = PHASE_ACTIVE
        if successor.started_at is None:
            successor.started_at = moment
        if evidence["open_task_ids"]:
            moved = int(
                _dispatch_tasks(
                    db, "sys.v1.task.set_phase",
                    {
                        "masterplan_id": plan.id,
                        "phase_id": successor.id,
                        "task_ids": evidence["open_task_ids"],
                    },
                    user_id=owner,
                ).get("attached") or 0
            )

    plan.phase = derive_legacy_phase(phases)
    db.commit()
    for row in (phase, successor):
        if row is not None:
            db.refresh(row)

    return {
        "completed": serialize_phase(phase),
        "activated": serialize_phase(successor) if successor is not None else None,
        "plan_phase": plan.phase,
        # What the review opens with. `early_by_days` is the owner's own trigger; the moved
        # tasks are the ones that did not happen when the plan said they would.
        "review": {
            "reason": REASON_WORK_COMPLETE if evidence["work_complete"] else REASON_WINDOW_ELAPSED,
            "early_by_days": evidence["early_by_days"],
            "moved_task_ids": evidence["open_task_ids"] if moved else [],
            "moved_to_phase_id": successor.id if (successor is not None and moved) else None,
        },
    }


def derive_legacy_phase(phases: list[PlanPhase]) -> int:
    """`master_plans.phase`, the integer that predates the layer, read off the layer.

    The frontier's ordinal; the last ordinal once everything is complete; 1 for a plan with
    no phases, which is the column's own default. Nothing else should write this column now.
    """
    if not phases:
        return 1
    frontier = frontier_phase(phases)
    if frontier is None:
        return max(int(row.ordinal or 0) for row in phases) or 1
    return int(frontier.ordinal or 1)
