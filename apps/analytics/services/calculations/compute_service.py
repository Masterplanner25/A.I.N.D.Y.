from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session
from AINDY.platform_layer.registry import get_symbol


def list_calculation_results(db: Session, *, user_id: str) -> list[Any]:
    """Return all CalculationResult rows for a user."""
    from apps.analytics.models import CalculationResult

    return (
        db.query(CalculationResult)
        .filter(CalculationResult.user_id == uuid.UUID(str(user_id)))
        .all()
    )


def _serialize_masterplan(plan: Any) -> dict[str, Any]:
    """Project a MasterPlan row onto a JSON-safe dict.

    The compute routes previously returned the ORM object itself, which the response
    envelope rendered as ``{}`` — callers could not read back so much as the new plan's
    id. Field selection mirrors the masterplan domain's own ``/apps/masterplans/``
    projection so the two surfaces agree.
    """
    def _iso(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    return {
        "id": plan.id,
        "status": plan.status,
        "posture": plan.posture,
        "version_label": plan.version_label,
        "is_active": plan.is_active,
        "is_origin": plan.is_origin,
        "start_date": _iso(plan.start_date),
        "target_date": _iso(plan.target_date),
        "duration_years": plan.duration_years,
        "locked_at": _iso(plan.locked_at),
        "created_at": _iso(plan.created_at),
    }


def list_masterplans_compute(db: Session, *, user_id: str) -> list[dict[str, Any]]:
    """Return all MasterPlan rows for a user (compute/legacy endpoint)."""
    MasterPlan = get_symbol("MasterPlan")
    if MasterPlan is None:
        return []

    plans = (
        db.query(MasterPlan)
        .filter(MasterPlan.user_id == uuid.UUID(str(user_id)))
        .order_by(MasterPlan.id)
        .all()
    )
    return [_serialize_masterplan(plan) for plan in plans]


def create_masterplan_compute(db: Session, *, data: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Create and persist a new MasterPlan from raw field data.

    ``MasterPlan(**data)`` used to be passed the request body verbatim, which could
    never succeed: the schema carried a ``name`` field the ORM has no column for
    (``TypeError: 'name' is an invalid keyword argument``), and the NOT NULL
    ``target_date`` column was never supplied. Both are handled here — ``target_date``
    is derived from the horizon exactly as ``create_masterplan_from_genesis`` does.
    """
    from datetime import timedelta

    MasterPlan = get_symbol("MasterPlan")
    if MasterPlan is None:
        raise RuntimeError("MasterPlan model is not registered")

    user_uuid = uuid.UUID(str(user_id))
    fields = dict(data)
    fields.pop("name", None)  # accepted historically; no corresponding column

    start_date = fields.get("start_date")
    duration_years = float(fields.get("duration_years") or 0)
    if start_date is not None and not fields.get("target_date"):
        fields["target_date"] = start_date + timedelta(days=int(duration_years * 365))

    # First plan for a user is the origin of their lineage — same rule the genesis
    # factory applies, so compute-created plans are structurally consistent with it.
    has_plans = (
        db.query(MasterPlan).filter(MasterPlan.user_id == user_uuid).first() is not None
    )
    fields.setdefault("is_origin", not has_plans)
    fields.setdefault("is_active", False)
    fields.setdefault("status", "draft")

    plan = MasterPlan(**fields)
    plan.user_id = user_uuid
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _serialize_masterplan(plan)
