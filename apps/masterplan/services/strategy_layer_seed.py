"""Seed a plan's objectives and phases from what Genesis already produced.

`STRATEGY_LAYER_SPEC` §8, step 2. Genesis emits both axes separately and always has — three
`core_domains` and five `phases` sit in `structure_json` on every locked plan, and until now
the phases were materialised as **tasks** while the domains were rendered as read-only text in
`GenesisDraftPreview.jsx` and stored nowhere.

★ **This seeds; it does not delete.** §8 says the five phase-as-task rows should be removed,
and they should — but not here, and the reason is a real ordering hazard the spec's step list
does not surface:

The live chain 12→13→14→15→16 is read by `eta_service._scope_plan_from_graph` via
`sys.v1.tasks.get_graph_context`, which derives `critical_depth` — the longest remaining
dependency chain — and uses it to set a **sequential floor** on the plan's ETA. Deleting those
tasks before something reads `plan_phases` collapses `critical_depth` to 1, the floor vanishes,
and the plan projects as though all five phases could run at once.

So §8's warning has a converse worth stating: *nothing may read `plan_phases` until the rows
have moved*, **and nothing may stop reading the tasks until something reads `plan_phases`.**
The delete belongs with the rewire (step 3), not with the seed.

Idempotent by name, so running it twice does not duplicate a plan's layer, and so a plan
locked before this existed can be backfilled with the same call new plans make.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher
from AINDY.platform_layer.user_ids import parse_user_id
from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.strategy_layer import PlanObjective, PlanPhase

logger = logging.getLogger(__name__)


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def seed_strategy_layer(
    db: Session, *, masterplan_id: int, user_id: Any = None
) -> dict[str, Any]:
    """Create the plan's objectives and phases from its `structure_json`.

    Returns what it created and what it found already there. Never raises on a plan with no
    structure — an imported or hand-made plan legitimately has neither axis, and that is an
    empty result rather than an error.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        return {"objectives": 0, "phases": 0, "reason": "plan not found"}

    structure = plan.structure_json if isinstance(plan.structure_json, dict) else {}
    uid = parse_user_id(user_id) if user_id is not None else plan.user_id

    objectives = _seed_objectives(db, plan, structure, uid)
    phases = _seed_phases(db, plan, structure, uid)
    db.commit()

    return {
        "masterplan_id": plan.id,
        "objectives": objectives["created"],
        "objectives_existing": objectives["existing"],
        "phases": phases["created"],
        "phases_existing": phases["existing"],
    }


def _seed_objectives(db, plan, structure: dict, uid) -> dict[str, int]:
    """`core_domains` are objectives in everything but name.

    *"Ethical AI Framework — to establish guidelines and standards for ethical AI development
    and deployment."* That is the Objective layer, already being generated, and currently
    rendered only as read-only text.
    """
    domains = structure.get("core_domains")
    if not isinstance(domains, list):
        return {"created": 0, "existing": 0}

    existing = {
        row.name.lower()
        for row in db.query(PlanObjective).filter(
            PlanObjective.masterplan_id == plan.id
        ).all()
    }
    created = 0
    for ordinal, domain in enumerate(domains, start=1):
        if not isinstance(domain, dict):
            continue
        name = _clean(domain.get("name"))
        if not name or name.lower() in existing:
            continue
        db.add(
            PlanObjective(
                masterplan_id=plan.id,
                user_id=uid,
                name=name,
                intent=_clean(domain.get("intent"), 2000) or None,
                ordinal=ordinal,
            )
        )
        existing.add(name.lower())
        created += 1
    return {"created": created, "existing": len(existing) - created}


def _seed_phases(db, plan, structure: dict, uid) -> dict[str, int]:
    """`phases` are the when-axis, carried with their order as an explicit edge.

    ★ `depends_on_phase_id` is chained here rather than left to `ordinal`. The order is
    load-bearing — it is what sets the plan's sequential ETA floor — and an ordinal is a
    display concern that any reorder would quietly change.
    """
    phases = structure.get("phases")
    if not isinstance(phases, list):
        return {"created": 0, "existing": 0}

    already = (
        db.query(PlanPhase)
        .filter(PlanPhase.masterplan_id == plan.id)
        .order_by(PlanPhase.ordinal.asc())
        .all()
    )
    existing = {row.name.lower() for row in already}
    # Chain onto the end of whatever is already there, so a partial seed completes rather
    # than starting a second disconnected chain.
    previous = already[-1] if already else None

    created = 0
    for ordinal, phase in enumerate(phases, start=1):
        if not isinstance(phase, dict):
            continue
        name = _clean(phase.get("name"))
        if not name or name.lower() in existing:
            continue
        duration = phase.get("duration_months")
        row = PlanPhase(
            masterplan_id=plan.id,
            user_id=uid,
            name=name,
            description=_clean(phase.get("description"), 2000) or None,
            ordinal=ordinal,
            duration_months=int(duration) if isinstance(duration, (int, float)) else None,
            depends_on_phase_id=previous.id if previous is not None else None,
        )
        db.add(row)
        # Flush so the next phase can reference this one's generated id.
        db.flush()
        existing.add(name.lower())
        previous = row
        created += 1
    return {"created": created, "existing": len(existing) - created}


def attach_tasks_to_phases(
    db: Session, *, masterplan_id: int, user_id: Any = None
) -> dict[str, Any]:
    """Give the plan's real tasks a phase, matching §8's treatment of task 17.

    Only tasks that are actually work are touched. The five phase-as-task rows are left
    entirely alone: they are what step 3 removes, and rewriting them here would make that
    removal harder to reason about, not easier.

    Everything lands on the first phase, because nothing in the data says otherwise — the
    tasks carry no phase information, and inventing one would be a guess wearing the shape of
    a migration. A task can be moved afterwards; a wrong guess recorded silently cannot be
    noticed.
    """
    phases = (
        db.query(PlanPhase)
        .filter(PlanPhase.masterplan_id == int(masterplan_id))
        .order_by(PlanPhase.ordinal.asc())
        .all()
    )
    if not phases:
        return {"attached": 0, "reason": "no phases to attach to"}

    # ★ Fall back to the plan's owner rather than dispatching without one. The task syscalls
    # refuse an unauthenticated tenant, and this function is non-fatal — so a missing user_id
    # would attach nothing, log a warning, and report success. Deriving it removes the only
    # way this can silently do nothing.
    if user_id is None:
        plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
        user_id = plan.user_id if plan is not None else None
    if user_id is None:
        return {"attached": 0, "reason": "plan has no owner to act as"}

    phase_names = {row.name.lower() for row in phases}
    first = phases[0]

    # Listed and written through task syscalls rather than by importing `apps.tasks` —
    # masterplan reaches tasks by syscall, pinned by
    # `test_masterplan_bootstrap_keeps_only_identity_as_direct_app_dependency`.
    tasks = _dispatch_tasks(
        db, "sys.v1.task.list_for_masterplan",
        {"masterplan_id": int(masterplan_id)}, user_id=user_id,
    ).get("tasks") or []

    unattached = [t for t in tasks if not t.get("phase_id")]
    skipped = [t for t in unattached if (t.get("name") or "").strip().lower() in phase_names]
    attachable = [t for t in unattached if t not in skipped]

    result = _dispatch_tasks(
        db, "sys.v1.task.set_phase",
        {
            "masterplan_id": int(masterplan_id),
            "phase_id": first.id,
            "task_ids": [t["id"] for t in attachable if t.get("id") is not None],
        },
        user_id=user_id,
    )
    return {
        "attached": int(result.get("attached") or 0),
        "skipped_phase_rows": len(skipped),
        "phase_id": first.id,
    }


def _dispatch_tasks(db, name: str, payload: dict, *, user_id: Any) -> dict[str, Any]:
    """Call a task syscall, returning its data or an empty dict.

    Non-fatal on purpose: seeding a plan's layer must not fail because a task write was
    refused. The objectives and phases are the durable half; an unattached task is visible and
    fixable, a half-seeded layer is neither.
    """
    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id) if user_id else "",
        capabilities=["task.read", "task.update", "task.delete"],
        trace_id="",
        metadata={"_db": db},
    )
    try:
        result = get_dispatcher().dispatch(name, payload, ctx)
    except Exception as exc:
        logger.warning("[strategy] %s failed: %s", name, exc)
        return {}
    # Lowercase syscall envelope, not the uppercase flow one.
    if result.get("status") != "success":
        logger.warning("[strategy] %s refused: %s", name, result.get("error"))
        return {}
    return result.get("data") or {}


# ── Retiring the phases-as-tasks ──────────────────────────────────────────────────────

def retire_phase_as_task_rows(
    db: Session, *, masterplan_id: int, apply: bool = False
) -> dict[str, Any]:
    """Remove the task rows that are really phases, now that `plan_phases` owns them.

    `STRATEGY_LAYER_SPEC` §8 step 3. These rows are not work — they were never actionable and
    never completable, and leaving them keeps the exact ambiguity the layer exists to remove.

    ★ **Dry-run by default, and it refuses more than it deletes.** §8 says to write this by
    hand and read it before running it; `apply=False` is that instruction made mechanical. A
    row is retired only when *every* one of these holds:

    * the plan has `plan_phases`, so something else owns the representation now
    * the task's name matches one of them
    * it is **not completed** — a completed row is real work someone did, whatever it is named
    * nothing outside the retiring set **depends on it** — deleting a row a real task is
      blocked behind would silently unblock that task

    The last two are the ones that matter. Both are refusals rather than filters: a row that
    trips them is reported, not quietly skipped, because either means an assumption behind
    this migration is wrong for that plan.
    """
    phases = (
        db.query(PlanPhase).filter(PlanPhase.masterplan_id == int(masterplan_id)).all()
    )
    if not phases:
        return {
            "retired": 0,
            "applied": False,
            "reason": "plan has no phases — seed the layer before retiring the task rows",
        }

    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    user_id = plan.user_id if plan is not None else None
    if user_id is None:
        return {"retired": 0, "applied": False, "reason": "plan has no owner to act as"}

    tasks = _dispatch_tasks(
        db, "sys.v1.task.list_for_masterplan",
        {"masterplan_id": int(masterplan_id)}, user_id=user_id,
    ).get("tasks") or []

    phase_names = {row.name.strip().lower() for row in phases}
    candidates = [
        t for t in tasks if (t.get("name") or "").strip().lower() in phase_names
    ]
    candidate_ids = {t.get("id") for t in candidates}

    completed = [t for t in candidates if t.get("status") == "completed"]
    # A dependent OUTSIDE the set. Dependencies among the candidates themselves are the chain
    # being retired wholesale, which is fine; a real task blocked behind one is not.
    outside_dependents = [
        t for t in tasks
        if t.get("id") not in candidate_ids
        and any(
            (dep or {}).get("task_id") in candidate_ids
            for dep in (t.get("depends_on") or [])
        )
    ]

    refusals = []
    if completed:
        refusals.append(
            f"{len(completed)} phase-named task(s) are completed — real work, not a phase row"
        )
    if outside_dependents:
        refusals.append(
            f"{len(outside_dependents)} task(s) outside the set depend on these rows"
        )

    report = {
        "candidates": [
            {"id": t.get("id"), "name": t.get("name"), "status": t.get("status")}
            for t in candidates
        ],
        "candidate_count": len(candidates),
        "refusals": refusals,
        "applied": False,
        "retired": 0,
    }
    if refusals or not candidates:
        return report
    if not apply:
        report["reason"] = "dry run — pass apply=True to delete"
        return report

    deleted = _dispatch_tasks(
        db, "sys.v1.task.delete_many",
        {"masterplan_id": int(masterplan_id), "task_ids": sorted(candidate_ids)},
        user_id=user_id,
    )
    report["retired"] = int(deleted.get("deleted") or 0)
    report["applied"] = True
    return report
