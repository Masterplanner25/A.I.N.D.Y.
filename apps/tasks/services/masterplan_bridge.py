from __future__ import annotations

import uuid

from fastapi import HTTPException


def assert_masterplan_owned_via_syscall(masterplan_id, user_id: str, db) -> None:
    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=["masterplan.read"],
        trace_id="",
        metadata={"_db": db},
    )
    result = get_dispatcher().dispatch(
        "sys.v1.masterplan.assert_owned",
        {"masterplan_id": str(masterplan_id), "user_id": str(user_id)},
        ctx,
    )
    if result["status"] != "success":
        raise ValueError(f"masterplan_not_found:{masterplan_id}")


def get_active_masterplan_via_syscall(user_id: str, db):
    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=["masterplan.read"],
        trace_id="",
        metadata={"_db": db},
    )
    try:
        result = get_dispatcher().dispatch(
            "sys.v1.masterplan.get_active",
            {"user_id": str(user_id)},
            ctx,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "syscall_unavailable", "message": str(exc)},
        ) from exc
    if result["status"] != "success":
        raise HTTPException(
            status_code=503,
            detail={"error": "syscall_unavailable", "message": result.get("error", "")},
        )
    return (result.get("data") or {}).get("masterplan")


def get_eta_via_syscall(masterplan_id, user_id: str, db):
    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=["masterplan.read"],
        trace_id="",
        metadata={"_db": db},
    )
    try:
        result = get_dispatcher().dispatch(
            "sys.v1.masterplan.get_eta",
            {"masterplan_id": str(masterplan_id), "user_id": str(user_id)},
            ctx,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "syscall_unavailable", "message": str(exc)},
        ) from exc
    if result["status"] != "success":
        raise HTTPException(
            status_code=503,
            detail={"error": "syscall_unavailable", "message": result.get("error", "")},
        )
    return (result.get("data") or {}).get("eta")


def recalculate_wcu_via_syscall(masterplan_id, user_id: str, db):
    """Recompute the plan's WCU (Work Complexity Units) + phase via the masterplan syscall.

    Sibling of ``get_eta_via_syscall`` — same plan-progress recalc surface, called on the same
    task-completion trigger. Non-fatal to the caller: returns ``None`` on any dispatch failure so
    a WCU hiccup never blocks task completion (the daily scheduler sweep will reconcile).
    """
    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=["masterplan.read"],
        trace_id="",
        metadata={"_db": db},
    )
    try:
        result = get_dispatcher().dispatch(
            "sys.v1.masterplan.recalculate_wcu",
            {"masterplan_id": str(masterplan_id), "user_id": str(user_id)},
            ctx,
        )
    except Exception:
        return None
    if result.get("status") != "success":
        return None
    return (result.get("data") or {}).get("wcu")


def resolve_phase_via_syscall(
    masterplan_id, user_id: str, db, phase_id: str | None = None, strategy_id: str | None = None,
) -> tuple[str | None, str | None]:
    """`(phase_id, strategy_id)` a new task on this plan belongs to, decided by masterplan.

    ★ Non-fatal when the plan has no layer (returns Nones) and fatal when a *requested* phase
    or strategy is not on the plan — the first is a plan that predates phases, the second is a
    caller error. A task with no phase is invisible to the strategy layer, so the default is
    the plan's current phase rather than nothing; a task under a strategy is scheduled where
    the strategy is.
    """
    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=["masterplan.read"],
        trace_id="",
        metadata={"_db": db},
    )
    payload = {"masterplan_id": str(masterplan_id)}
    if phase_id:
        payload["phase_id"] = str(phase_id)
    if strategy_id:
        payload["strategy_id"] = str(strategy_id)
    result = get_dispatcher().dispatch("sys.v1.masterplan.resolve_phase", payload, ctx)
    if result["status"] != "success":
        if strategy_id:
            raise ValueError(f"strategy_not_on_plan:{strategy_id}")
        if phase_id:
            raise ValueError(f"phase_not_on_plan:{phase_id}")
        return None, None
    data = result.get("data") or {}
    return data.get("phase_id"), data.get("strategy_id")

