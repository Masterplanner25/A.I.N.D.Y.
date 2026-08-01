"""Freelance domain syscall handlers.

Exposes the freelance domain's cross-domain read seam. Currently: the revenue performance
signals the analytics/Infinity support state fetches via `sys.v1.freelance.get_performance_signals`
(re-tether — mirrors the social domain's `get_performance_signals` syscall).
"""
from __future__ import annotations

from AINDY.kernel.syscall_registry import SyscallContext, register_syscall


def _session_from_context(ctx: SyscallContext):
    from AINDY.db.database import SessionLocal

    external_db = ctx.metadata.get("_db")
    if external_db is not None:
        return external_db, False
    return SessionLocal(), True


def _handle_freelance_performance_signals(payload: dict, ctx: SyscallContext) -> dict:
    from apps.freelance.services.freelance_performance_service import (
        get_freelance_performance_signals,
    )

    db, owns_session = _session_from_context(ctx)
    try:
        signals = list(
            get_freelance_performance_signals(
                db,
                user_id=payload.get("user_id") or ctx.user_id or None,
                limit=int(payload.get("limit", 3) or 3),
            )
            or []
        )
        return {"signals": signals, "count": len(signals)}
    finally:
        if owns_session:
            db.close()


def _handle_freelance_goal_metric(payload: dict, ctx: SyscallContext) -> dict:
    """Cumulative realized revenue, for MasterPlan goal attainment.

    Distinct from ``get_performance_signals``, which returns the top-N advisory signal
    list and discards the counters — goal attainment needs a scalar, so this is a
    separate contract rather than a reuse.

    Computed live from delivered orders rather than read from ``revenue_metrics``:
    that table carries no ``user_id`` (it is a global snapshot), so it cannot answer a
    per-user goal. Same summation ``update_revenue_metrics`` performs, user-scoped.

    Scope note: answers **user-wide**, not plan-scoped, even though ``FreelanceOrder``
    carries ``masterplan_id``. Orders are rarely plan-linked in practice, so scoping to
    the plan would report 0 for almost everyone. The scope used is returned explicitly
    rather than left implicit.
    """
    import uuid as _uuid

    from apps.freelance.models.freelance import FreelanceOrder

    unit = str(payload.get("unit") or "").strip().lower()
    if unit not in {"usd", "revenue"}:
        return {"supported": False, "unit": unit, "value": 0.0}

    user_id = payload.get("user_id") or ctx.user_id or None
    if not user_id:
        return {"supported": False, "unit": unit, "value": 0.0}

    db, owns_session = _session_from_context(ctx)
    try:
        query = db.query(FreelanceOrder).filter(
            FreelanceOrder.status == "delivered",
            FreelanceOrder.user_id == _uuid.UUID(str(user_id)),
        )
        total = sum(float(order.price or 0.0) for order in query.all())
        return {"supported": True, "unit": "usd", "value": float(total), "scope": "user"}
    finally:
        if owns_session:
            db.close()


def _handle_freelance_optimize_pricing(payload: dict, ctx: SyscallContext) -> dict:
    from apps.freelance.services.revenue_intelligence_service import RevenueIntelligenceService

    db, owns_session = _session_from_context(ctx)
    try:
        svc = RevenueIntelligenceService(db=db, user_id=ctx.user_id)
        if bool(payload.get("apply", False)):
            return svc.apply(trigger=payload.get("trigger", "agent"))
        return {"dry_run": True, **svc.plan()}
    finally:
        if owns_session:
            db.close()


def register_freelance_syscall_handlers() -> None:
    register_syscall(
        name="sys.v1.freelance.get_performance_signals",
        handler=_handle_freelance_performance_signals,
        capability="freelance.read",
        description="Recent realized-revenue signals for the Infinity support state (re-tether).",
        stable=False,
    )
    register_syscall(
        name="sys.v1.freelance.get_goal_metric",
        handler=_handle_freelance_goal_metric,
        capability="freelance.read",
        description="Cumulative realized revenue for MasterPlan goal attainment (unit: usd).",
        input_schema={
            "required": ["unit"],
            "properties": {
                "unit": {"type": "string"},
                "user_id": {"type": "string"},
                "masterplan_id": {"type": "integer"},
            },
        },
        stable=False,
    )
    register_syscall(
        name="sys.v1.freelance.optimize_pricing",
        handler=_handle_freelance_optimize_pricing,
        capability="freelance.optimize",
        description="Recommend/apply gated, revertible service-price adjustments from realized outcomes.",
        stable=False,
    )
