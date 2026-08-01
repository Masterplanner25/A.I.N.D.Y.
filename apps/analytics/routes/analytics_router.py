from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from apps.analytics.schemas.analytics import LinkedInRawInput
from AINDY.services.auth_service import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _with_execution_envelope(payload):
    envelope = to_envelope(
        eu_id=None,
        trace_id=None,
        status="SUCCESS",
        output=None,
        error=None,
        duration_ms=None,
        attempt_count=1,
    )
    if hasattr(payload, "status_code") and hasattr(payload, "body"):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        result = dict(data) if isinstance(data, dict) else dict(payload)
        result.setdefault("execution_envelope", envelope)
        return result
    return {"data": payload, "execution_envelope": envelope}


def _analytics_http_error(data):
    """Raise HTTPException if node encoded an HTTP error."""
    if isinstance(data, dict) and "_http_error" in data:
        err = data["_http_error"]
        raise HTTPException(status_code=err["status_code"], detail=err["detail"])


@router.post("/linkedin/manual")
@limiter.limit("30/minute")
async def ingest_linkedin_manual(
    request: Request,
    data: LinkedInRawInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.integration.masterplan_guard import assert_masterplan_owned_via_syscall
        from AINDY.runtime.flow_engine import run_flow

        assert_masterplan_owned_via_syscall(data.masterplan_id, user_id, db)

        result = run_flow(
            "analytics_linkedin_ingest",
            {"data": data.model_dump()},
            db=db,
            user_id=user_id,
        )
        if result.get("status") == "FAILED":
            error = result.get("error", "")
            if error.startswith("HTTP_"):
                parts = error.split(":", 1)
                raise HTTPException(
                    status_code=int(parts[0].replace("HTTP_", "")),
                    detail={"error": "masterplan_not_found", "message": parts[1] if len(parts) > 1 else error},
                )
            raise HTTPException(status_code=500, detail="Analytics ingest failed")
        return result.get("data")

    result = await execute_with_pipeline(
        request=request, route_name="analytics.linkedin.manual", handler=handler,
        user_id=user_id, metadata={"db": db}, input_payload=data.model_dump(),
    )
    return _with_execution_envelope(result)


@router.get("/masterplan/{masterplan_id}")
@limiter.limit("60/minute")
async def get_masterplan_analytics(
    request: Request,
    masterplan_id: int,
    period_type: str | None = None,
    platform: str | None = None,
    scope_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.integration.masterplan_guard import assert_masterplan_owned_via_syscall
        from AINDY.runtime.flow_engine import run_flow

        assert_masterplan_owned_via_syscall(masterplan_id, user_id, db)

        result = run_flow(
            "analytics_masterplan_get",
            {"masterplan_id": masterplan_id, "period_type": period_type, "platform": platform, "scope_type": scope_type},
            db=db, user_id=user_id,
        )
        if result.get("status") == "FAILED":
            error = result.get("error", "")
            if "404" in error:
                raise HTTPException(status_code=404, detail={"error": "masterplan_not_found", "message": "MasterPlan not found"})
            raise HTTPException(status_code=500, detail="Analytics fetch failed")
        return result.get("data")

    return await execute_with_pipeline(
        request=request, route_name="analytics.masterplan.get", handler=handler,
        user_id=user_id, metadata={"db": db},
    )


@router.get("/masterplan/{masterplan_id}/summary")
@limiter.limit("60/minute")
async def get_masterplan_summary(
    request: Request,
    masterplan_id: int,
    group_by: str | None = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.integration.masterplan_guard import assert_masterplan_owned_via_syscall
        from AINDY.runtime.flow_engine import run_flow

        assert_masterplan_owned_via_syscall(masterplan_id, user_id, db)

        result = run_flow(
            "analytics_masterplan_summary",
            {"masterplan_id": masterplan_id, "group_by": group_by},
            db=db, user_id=user_id,
        )
        if result.get("status") == "FAILED":
            error = result.get("error", "")
            if "404" in error:
                raise HTTPException(status_code=404, detail={"error": "masterplan_not_found", "message": "MasterPlan not found"})
            raise HTTPException(status_code=500, detail="Analytics summary failed")
        return result.get("data")

    return await execute_with_pipeline(
        request=request, route_name="analytics.masterplan.summary", handler=handler,
        user_id=user_id, metadata={"db": db},
    )


@router.get("/kpi-weights")
@limiter.limit("60/minute")
async def get_kpi_weights(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.kpi_weight_service import (
            get_effective_weights,
            get_or_create_user_weights,
        )

        row = get_or_create_user_weights(db, user_id)
        return {
            "weights": get_effective_weights(db, user_id),
            "adapted_count": int(row.adapted_count or 0),
            "last_adapted_at": row.last_adapted_at.isoformat() if row.last_adapted_at else None,
            "is_personalized": bool((row.adapted_count or 0) > 0),
        }

    result = await execute_with_pipeline(
        request=request,
        route_name="analytics.kpi_weights.get",
        handler=handler,
        user_id=user_id,
        metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.post("/kpi-weights/adapt")
@limiter.limit("5/minute")
async def adapt_kpi_weights_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.kpi_weight_service import adapt_kpi_weights

        return adapt_kpi_weights(db, user_id)

    result = await execute_with_pipeline(
        request=request,
        route_name="analytics.kpi_weights.adapt",
        handler=handler,
        user_id=user_id,
        metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.get("/policy-thresholds")
@limiter.limit("30/minute")
async def get_policy_thresholds(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.policy_adaptation_service import (
            get_effective_thresholds,
            get_or_create_thresholds,
        )

        result = dict(get_effective_thresholds(db, user_id))
        row = get_or_create_thresholds(db, user_id)
        result["adapted_count"] = int(row.adapted_count or 0)
        result["last_adapted_at"] = row.last_adapted_at.isoformat() if row.last_adapted_at else None
        return result

    result = await execute_with_pipeline(
        request=request,
        route_name="analytics.policy_thresholds.get",
        handler=handler,
        user_id=user_id,
        metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.post("/policy-thresholds/adapt")
@limiter.limit("5/minute")
async def adapt_policy_thresholds_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.policy_adaptation_service import adapt_policy_thresholds

        return adapt_policy_thresholds(db, user_id)

    result = await execute_with_pipeline(
        request=request,
        route_name="analytics.policy_thresholds.adapt",
        handler=handler,
        user_id=user_id,
        metadata={"db": db},
    )
    return _with_execution_envelope(result)


# ── Three-axis Infinity score — observability (Phase A) ───────────────────────
# Volume / Worth / Trajectory computed alongside master_score, for observation only.
# See docs/architecture/INFINITY_SCORE_MODEL.md. Never drives canonical scoring.

from pydantic import BaseModel  # noqa: E402


class ValueDeclarationRequest(BaseModel):
    target_type: str            # task | masterplan | project | other
    declared_value: float
    target_id: str | None = None
    label: str | None = None
    kind: str = "strategic"     # monetary_potential | intrinsic | strategic
    note: str | None = None


@router.get("/three-axis")
@limiter.limit("60/minute")
async def get_three_axis_snapshot(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Observability snapshot of the Volume / Worth / Trajectory axes alongside the
    (unchanged) master_score. Phase A: measurement only — does not drive scoring."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.three_axis_service import compute_three_axes

        return compute_three_axes(db, user_id)

    result = await execute_with_pipeline(
        request=request, route_name="analytics.three_axis", handler=handler,
        user_id=user_id, metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.post("/worth/declare")
@limiter.limit("30/minute")
async def declare_worth(
    request: Request,
    body: ValueDeclarationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Declare what a task / masterplan / project is worth (the Worth axis's prior)."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.value_declaration_service import record_value_declaration

        try:
            return record_value_declaration(
                db, user_id=user_id, target_type=body.target_type,
                declared_value=body.declared_value, target_id=body.target_id,
                label=body.label, kind=body.kind, note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    result = await execute_with_pipeline(
        request=request, route_name="analytics.worth.declare", handler=handler,
        user_id=user_id, metadata={"db": db}, input_payload=body.model_dump(),
    )
    return _with_execution_envelope(result)


@router.get("/worth/declarations")
@limiter.limit("60/minute")
async def list_worth_declarations(
    request: Request,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List this user's declared-worth entries."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.value_declaration_service import list_value_declarations

        items = list_value_declarations(db, user_id, limit=limit)
        return {"declarations": items, "count": len(items)}

    result = await execute_with_pipeline(
        request=request, route_name="analytics.worth.declarations", handler=handler,
        user_id=user_id, metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.get("/goal-attainment")
@limiter.limit("60/minute")
async def get_goal_attainment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Resolve the active plan's declared goal against real domain signals.

    Phase 0 of the goal-attainment work (see
    docs/handoffs/MASTERPLAN_GOAL_ATTAINMENT_SPEC.md): read-only and **not wired into
    scoring** — `masterplan_progress` is unchanged. This route exists so the resolver
    can be inspected against real plans before it influences anything.

    `supported: false` is a normal answer (undeclared goal, unsupported unit, degraded
    domain), not an error — it carries a `reason` and means "the existing formula
    applies". Only `tasks` resolves today; `supported_units` reports the live set.
    """
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.integration.goal_attainment import (
            resolve_for_active_plan,
            supported_units,
        )

        result = resolve_for_active_plan(db, user_id)
        result["supported_units"] = supported_units()
        return result

    result = await execute_with_pipeline(
        request=request, route_name="analytics.goal_attainment", handler=handler,
        user_id=user_id, metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.get("/three-axis/shadow")
@limiter.limit("60/minute")
async def get_three_axis_shadow_report(
    request: Request,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Three-axis shadow soak report (Phase B): recent recorded axes next to master_score
    + mean-per-axis summary (the divergence signal). Records only accrue while
    AINDY_INFINITY_THREE_AXIS_SHADOW is on."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.three_axis_service import three_axis_shadow_report

        return three_axis_shadow_report(db, user_id=user_id, limit=limit)

    result = await execute_with_pipeline(
        request=request, route_name="analytics.three_axis.shadow", handler=handler,
        user_id=user_id, metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.get("/three-axis/advisory")
@limiter.limit("60/minute")
async def get_three_axis_advisory_preview(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Advisory preview (Phase C): what the Worth+Trajectory blend *would* make master_score,
    vs. the behavioral anchor, from this user's current KPIs. Read-only — never writes the
    score. The blend only *moves* the persisted score while AINDY_INFINITY_THREE_AXIS_ADVISORY
    is on (default off); this route works either way so operators can compare before flipping."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.analytics.services.scoring.three_axis_composition import preview_advisory

        return preview_advisory(db, user_id)

    result = await execute_with_pipeline(
        request=request, route_name="analytics.three_axis.advisory", handler=handler,
        user_id=user_id, metadata={"db": db},
    )
    return _with_execution_envelope(result)
