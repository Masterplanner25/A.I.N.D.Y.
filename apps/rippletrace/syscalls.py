"""Rippletrace domain syscall handlers."""
from __future__ import annotations

import uuid

from AINDY.kernel.syscall_registry import SyscallContext, register_syscall


def _session_from_context(ctx: SyscallContext):
    from AINDY.db.database import SessionLocal

    external_db = ctx.metadata.get("_db") or ctx.metadata.get("db")
    if external_db is not None:
        return external_db, False
    return SessionLocal(), True


def _handle_rippletrace_list_pings(payload: dict, ctx: SyscallContext) -> dict:
    from apps.rippletrace.models import PingDB

    user_id = payload.get("user_id") or ctx.user_id
    limit = int(payload.get("limit") or 10)

    db, owns_session = _session_from_context(ctx)
    try:
        pings = (
            db.query(PingDB)
            .filter(PingDB.user_id == uuid.UUID(str(user_id)))
            .order_by(PingDB.date_detected.desc())
            .limit(limit)
            .all()
        )
        return {
            "pings": [
                {
                    "ping_type": ping.ping_type,
                    "source_platform": ping.source_platform,
                    "summary": ping.connection_summary,
                    "date_detected": ping.date_detected.isoformat() if ping.date_detected else None,
                }
                for ping in pings
            ]
        }
    finally:
        if owns_session:
            db.close()


def _handle_log_ripple_event(payload: dict, ctx: SyscallContext) -> dict:
    from apps.rippletrace.public import log_ripple_event as _log_ripple

    event_type = payload.get("event_type")
    user_id = payload.get("user_id") or ctx.user_id
    source = payload.get("source")
    data = payload.get("data") or {}

    if not event_type:
        raise ValueError("sys.v1.rippletrace.log_ripple_event requires 'event_type'")

    event = {
        "ping_type": event_type,
        "source_platform": source,
        **data,
    }

    db, owns_session = _session_from_context(ctx)
    try:
        result = _log_ripple(
            db=db,
            event=event,
            user_id=user_id,
        )
        return {"logged": True, "result": result}
    finally:
        if owns_session:
            db.close()


def _handle_ripple_performance_signals(payload: dict, ctx: SyscallContext) -> dict:
    from apps.rippletrace.services.ripple_performance_service import (
        get_ripple_performance_signals,
    )

    db, owns_session = _session_from_context(ctx)
    try:
        signals = get_ripple_performance_signals(
            db,
            user_id=payload.get("user_id") or ctx.user_id or None,
            limit=int(payload.get("limit", 3) or 3),
        )
        return {"signals": signals, "count": len(signals)}
    finally:
        if owns_session:
            db.close()


def _handle_ripple_goal_metric(payload: dict, ctx: SyscallContext) -> dict:
    from apps.rippletrace.services.ripple_performance_service import get_goal_metric

    db, owns_session = _session_from_context(ctx)
    try:
        return get_goal_metric(
            db,
            unit=str(payload.get("unit") or ""),
            user_id=payload.get("user_id") or ctx.user_id or None,
        )
    finally:
        if owns_session:
            db.close()


# ── Archive steps, for archive_published_work_v1.nd ──────────────────────────────────────
# One syscall per step of `content_archive.archive_step`, each for the run's own user (never a
# payload id). The payload may lower the batch (`limit`, at most `BATCH`). Their names are chosen so the capability the runtime infers for a .nd's sys()
# (`store_`/`update_`/`write_` → `rippletrace.write`) is the one each requires.


def _archive_step(step):
    def _handle(payload: dict, ctx: SyscallContext) -> dict:
        if not ctx.user_id:
            raise ValueError("an archive step needs the run's user")
        from apps.rippletrace.services.content_archive import BATCH

        limit = max(1, min(int(payload.get("limit") or BATCH), BATCH))
        db, owns_session = _session_from_context(ctx)
        try:
            return step(db, ctx.user_id, limit)
        finally:
            if owns_session:
                db.close()

    return _handle


def _reclean(db, user_id, limit) -> dict:
    from apps.rippletrace.services.content_archive import reclean_stored

    return {"recleaned": reclean_stored(db, user_id=user_id)}


def _fetch(db, user_id, limit) -> dict:
    from apps.rippletrace.services.content_archive import backfill_content

    return backfill_content(db, user_id=user_id, limit=limit)


def _collapse(db, user_id, limit) -> dict:
    from apps.rippletrace.services.content_archive import collapse_cross_posts

    return {"collapsed": collapse_cross_posts(db, user_id=user_id)}


def _remember(db, user_id, limit) -> dict:
    from apps.rippletrace.services.content_archive import remember_content

    return remember_content(db, user_id=user_id, limit=limit)


ARCHIVE_STEP_SYSCALLS = {
    "sys.v1.rippletrace.update_stored_text": (_reclean, "Re-clean stored text of the caller's published pieces."),
    "sys.v1.rippletrace.store_published_text": (_fetch, "Fetch and store the text of a batch of the caller's published pieces."),
    "sys.v1.rippletrace.update_cross_posts": (_collapse, "Keep one memory copy of each of the caller's cross-posted pieces."),
    "sys.v1.rippletrace.write_published_memory": (_remember, "Write memory for a batch of the caller's pieces whose text changed."),
}


def register_rippletrace_syscall_handlers() -> None:
    for name, (step, description) in ARCHIVE_STEP_SYSCALLS.items():
        register_syscall(
            name=name,
            handler=_archive_step(step),
            capability="rippletrace.write",
            description=description,
            stable=False,
        )
    register_syscall(
        name="sys.v1.rippletrace.log_ripple_event",
        handler=_handle_log_ripple_event,
        capability="rippletrace.write",
        description="Log a rippletrace event through the rippletrace domain.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.rippletrace.list_recent_pings",
        handler=_handle_rippletrace_list_pings,
        capability="rippletrace.read",
        description="List recent pings for a user.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.rippletrace.get_performance_signals",
        handler=_handle_ripple_performance_signals,
        capability="rippletrace.read",
        description="Advisory signals about how published content is travelling (reach beyond your own audience).",
        stable=False,
    )
    register_syscall(
        name="sys.v1.rippletrace.get_goal_metric",
        handler=_handle_ripple_goal_metric,
        capability="rippletrace.read",
        description="Cumulative rippletrace counters for MasterPlan goal attainment (playbooks).",
        stable=False,
    )
