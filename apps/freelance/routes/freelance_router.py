import json as _json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline, execute_with_pipeline_sync
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from apps.freelance.schemas.freelance import (
    ActionIntakeRequest,
    FeedbackCreate,
    FreelanceDeliveryConfigUpdate,
    FreelanceOrderCreate,
    FulfillOrderRequest,
    LeadIntakeRequest,
    RefundRequest,
    SubscriptionCancelRequest,
)
from AINDY.services.auth_service import get_current_user

router = APIRouter(prefix="/freelance", tags=["Freelance"])
logger = logging.getLogger(__name__)


def _require_idempotency_key(key: str | None) -> str:
    """Reject a mutating request that carries no Idempotency-Key.

    **Call this from inside the pipeline handler, never above it.** The runtime's route
    guard cannot distinguish a deliberate HTTPException from a route that bypassed the
    pipeline, so anything raised before pipeline entry is re-raised as
    RouteExecutionViolation — the client receives an opaque 500 rather than being told
    the header is missing. Every one of these checks used to sit above the handler.
    """
    if not key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
    return key


def _trigger_delivery_confirmation_hooks(
    db: Session,
    *,
    order_data: dict,
    user_id: str,
) -> None:
    task_id = order_data.get("task_id")
    try:
        from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

        ctx = SyscallContext(
            execution_unit_id=str(uuid.uuid4()),
            user_id=str(user_id),
            capabilities=["task.read", "task.complete", "score.recalculate"],
            trace_id="",
            metadata={"_db": db},
        )
        if task_id:
            task_result = get_dispatcher().dispatch(
                "sys.v1.task.get",
                {"task_id": int(task_id), "user_id": str(user_id)},
                ctx,
            )
            if task_result.get("status") == "success":
                task = ((task_result.get("data") or {}).get("task") or {})
                task_name = task.get("name")
                task_status = str(task.get("status") or "").lower()
                if task_name and task_status != "completed":
                    get_dispatcher().dispatch(
                        "sys.v1.task.complete",
                        {"task_name": task_name},
                        ctx,
                    )
        get_dispatcher().dispatch(
            "sys.v1.score.recalculate",
            {"trigger_event": "freelance_delivery_confirmed"},
            ctx,
        )
    except Exception as exc:
        logger.warning(
            "[freelance] delivery confirmation hooks failed (non-fatal): %s",
            exc,
        )

def _run_flow_freelance(flow_name: str, payload: dict, db: Session, user_id: str, *, return_full: bool = False):
    from AINDY.runtime.flow_engine import run_flow
    from apps.search.public import extract_flow_error

    try:
        result = run_flow(flow_name, payload, db=db, user_id=user_id)
    except RuntimeError as exc:
        error = str(exc or "")
        marker = error.find("HTTP_")
        if marker != -1:
            error = error[marker:]
            parts = error.split(":", 1)
            code = int(parts[0].replace("HTTP_", ""))
            msg = parts[1] if len(parts) > 1 else error
            raise HTTPException(status_code=code, detail=msg) from exc
        raise
    if result.get("status") == "FAILED":
        error = extract_flow_error(result)
        if error.startswith("HTTP_"):
            parts = error.split(":", 1)
            code = int(parts[0].replace("HTTP_", ""))
            msg = parts[1] if len(parts) > 1 else error
            raise HTTPException(status_code=code, detail=msg)
        raise HTTPException(status_code=500, detail=error or f"{flow_name} failed")
    return result if return_full else result.get("data")


def _execute_freelance(request: Request, route_name: str, handler, *, db: Session, user_id: str,
                       input_payload=None, success_status_code: int = 200):
    from apps.search.public import (
        build_ai_provider_unavailable_payload,
        is_circuit_open_detail,
    )

    result = execute_with_pipeline_sync(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        input_payload=input_payload or {},
        metadata={"db": db, "source": "freelance"},
        success_status_code=success_status_code,
        return_result=True,
    )
    if not result.success:
        detail = result.metadata.get("detail") or result.error or "Execution failed"
        if is_circuit_open_detail(detail):
            raise HTTPException(
                status_code=503,
                detail=build_ai_provider_unavailable_payload(detail),
                headers={"Retry-After": "60"},
            )
        raise HTTPException(
            status_code=int(result.metadata.get("status_code", 500)),
            detail=detail,
        )
    eu_id = result.metadata.get("eu_id")
    if eu_id is None:
        raise HTTPException(status_code=500, detail="Execution pipeline did not attach eu_id")
    data = result.data
    if isinstance(data, dict):
        data = dict(data)
        _envelope_status = "SUCCESS"
        if hasattr(result, "data") and isinstance(result.data, dict):
            _raw_status = str(result.data.get("status") or "").upper()
            if _raw_status in {"SUCCESS", "FAILURE", "FAILED", "WAITING", "QUEUED", "ERROR", "UNKNOWN"}:
                _envelope_status = _raw_status
        data.setdefault(
            "execution_envelope",
            to_envelope(
                eu_id=eu_id,
                trace_id=result.metadata.get("trace_id"),
                status=_envelope_status,
                output=None,
                error=result.metadata.get("error") or (
                    result.data.get("error") if isinstance(
                        getattr(result, "data", None), dict
                    ) else None
                ),
                duration_ms=None,
                attempt_count=None,
            ),
        )
    return data


def _do_create_freelance_order(
    db: Session,
    order: FreelanceOrderCreate,
    user_id: str,
    idempotency_key: str,
):
    result = _run_flow_freelance(
        "freelance_order_create",
        {"order": order.model_dump(), "idempotency_key": idempotency_key},
        db,
        user_id,
    )
    return result.get("data") if isinstance(result, dict) and "data" in result else result


def _do_deliver_order(db: Session, order_id: int, ai_output: str | None, user_id: str):
    result = _run_flow_freelance(
        "freelance_order_deliver",
        {"order_id": order_id, "ai_output": ai_output},
        db,
        user_id,
    )
    data = result.get("data") if isinstance(result, dict) and "data" in result else result
    if isinstance(data, dict):
        _trigger_delivery_confirmation_hooks(db, order_data=data, user_id=user_id)
    return data


def _do_update_delivery_configuration(
    db: Session,
    order_id: int,
    body: FreelanceDeliveryConfigUpdate,
    user_id: str,
):
    return _run_flow_freelance(
        "freelance_delivery_update",
        {
            "order_id": order_id,
            "delivery_type": body.delivery_type,
            "delivery_config": body.delivery_config,
        },
        db,
        user_id,
    )


def _do_collect_feedback(db: Session, feedback: FeedbackCreate, user_id: str):
    result = _run_flow_freelance("freelance_feedback_collect", {"feedback": feedback.model_dump()}, db, user_id)
    return result.get("data") if isinstance(result, dict) and "data" in result else result


def _do_update_metrics(db: Session, user_id: str):
    return _run_flow_freelance("freelance_metrics_update", {}, db, user_id)


def _do_generate_delivery(db: Session, order_id: int, user_id: str):
    return _run_flow_freelance("freelance_delivery_generate", {"order_id": order_id}, db, user_id)


def _do_issue_refund(
    db: Session,
    order_id: int,
    reason: str | None,
    user_id: str,
    idempotency_key: str,
):
    return _run_flow_freelance(
        "freelance_refund",
        {"order_id": order_id, "reason": reason, "idempotency_key": idempotency_key},
        db,
        user_id,
    )


def _do_cancel_subscription(db, order_id, reason, user_id):
    return _run_flow_freelance(
        "freelance_subscription_cancel",
        {"order_id": order_id, "reason": reason},
        db,
        user_id,
    )


def _do_client_lineage(db: Session, client_id: int, user_id: str):
    result = _run_flow_freelance("freelance_client_lineage", {"client_id": client_id}, db, user_id)
    return result.get("data") if isinstance(result, dict) and "data" in result else result


def _do_intake_from_lead(db: Session, intake: "LeadIntakeRequest", user_id: str, idempotency_key: str):
    result = _run_flow_freelance(
        "freelance_intake_from_lead",
        {"intake": intake.model_dump(), "idempotency_key": idempotency_key},
        db,
        user_id,
    )
    return result.get("data") if isinstance(result, dict) and "data" in result else result


def _do_onboard_client(db: Session, intake: "LeadIntakeRequest", user_id: str, idempotency_key: str):
    result = _run_flow_freelance(
        "freelance_client_onboarding",
        {"intake": intake.model_dump(), "idempotency_key": idempotency_key},
        db,
        user_id,
    )
    return result.get("data") if isinstance(result, dict) and "data" in result else result


def _do_fulfill_order(db: Session, order_id: int, body: "FulfillOrderRequest", user_id: str):
    result = _run_flow_freelance(
        "freelance_order_fulfillment",
        {"order_id": order_id, "ai_output": body.ai_output, "generated_by_ai": body.generated_by_ai},
        db,
        user_id,
    )
    return result.get("data") if isinstance(result, dict) and "data" in result else result


@router.post("/order", status_code=201)
@limiter.limit("30/minute")
def create_freelance_order(
    request: Request,
    order: FreelanceOrderCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    idempotency_key = request.headers.get("Idempotency-Key")
    def handler(_ctx):
        _require_idempotency_key(idempotency_key)
        return _do_create_freelance_order(db, order, user_id, idempotency_key)
    result = _execute_freelance(
        request,
        "freelance.order.create",
        handler,
        db=db,
        user_id=user_id,
        input_payload={**order.model_dump(), "idempotency_key": idempotency_key},
        success_status_code=201,
    )
    if isinstance(result, dict):
        result = dict(result)
        idempotency = result.pop("_idempotency", {})
        status_code = 201 if idempotency.get("created", True) else 200
        return JSONResponse(status_code=status_code, content=jsonable_encoder(result))
    return result


@router.post("/deliver/{order_id}")
@limiter.limit("30/minute")
def deliver_order(
    request: Request,
    order_id: int,
    ai_output: str | None = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_deliver_order(db, order_id, ai_output, user_id)
    return _execute_freelance(
        request,
        "freelance.order.deliver",
        handler,
        db=db,
        user_id=user_id,
        input_payload={"order_id": order_id, "ai_output": ai_output},
    )


@router.put("/delivery/{order_id}")
@limiter.limit("30/minute")
def update_delivery_configuration(
    request: Request,
    order_id: int,
    body: FreelanceDeliveryConfigUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_update_delivery_configuration(db, order_id, body, user_id)
    return _execute_freelance(
        request,
        "freelance.delivery.update",
        handler,
        db=db,
        user_id=user_id,
        input_payload={
            "order_id": order_id,
            "delivery_type": body.delivery_type,
            "delivery_config": body.delivery_config,
        },
    )


@router.post("/feedback")
@limiter.limit("30/minute")
def collect_feedback(
    request: Request,
    feedback: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_collect_feedback(db, feedback, user_id)
    return _execute_freelance(
        request,
        "freelance.feedback.collect",
        handler,
        db=db,
        user_id=user_id,
        input_payload=feedback.model_dump(),
    )


class PricingRevertRequest(BaseModel):
    recommendation_id: int


@router.post("/pricing/optimize")
@limiter.limit("15/minute")
def optimize_pricing(
    request: Request,
    apply: bool = Query(False, description="Persist price changes. Default false = dry-run preview."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Revenue Intelligence Loop: recommend (and optionally apply) gated, revertible
    service-price adjustments from realized outcomes. Apply writes an internal default
    price for future quotes — it never changes an existing order or charges a customer."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.freelance.services.revenue_intelligence_service import RevenueIntelligenceService
        svc = RevenueIntelligenceService(db=db, user_id=user_id)
        if apply:
            return svc.apply(trigger="manual")
        return {"dry_run": True, **svc.plan()}

    return _execute_freelance(
        request, "freelance.pricing.optimize", handler, db=db, user_id=user_id,
        input_payload={"apply": apply},
    )


@router.post("/pricing/revert")
@limiter.limit("15/minute")
def revert_pricing(
    request: Request,
    body: PricingRevertRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Restore the default price that was in effect before an applied recommendation."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.freelance.services.revenue_intelligence_service import RevenueIntelligenceService
        return RevenueIntelligenceService(db=db, user_id=user_id).revert(body.recommendation_id)

    return _execute_freelance(
        request, "freelance.pricing.revert", handler, db=db, user_id=user_id,
        input_payload=body.model_dump(),
    )


@router.get("/pricing/recommendations")
@limiter.limit("60/minute")
def list_pricing_recommendations(
    request: Request,
    limit: int = Query(20, description="Max recommendations to return."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List this user's pricing recommendation runs (decisions, status, revert state)."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.freelance.services.revenue_intelligence_service import RevenueIntelligenceService
        rows = RevenueIntelligenceService(db=db, user_id=user_id).history(limit=limit)
        return {"recommendations": rows, "count": len(rows)}

    return _execute_freelance(request, "freelance.pricing.recommendations", handler, db=db, user_id=user_id)


@router.get("/pricing")
@limiter.limit("60/minute")
def get_pricing_catalog(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """The studio's current default price per service type (the apply target)."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.freelance.services.revenue_intelligence_service import RevenueIntelligenceService
        prices = RevenueIntelligenceService(db=db, user_id=user_id).catalog()
        return {"prices": prices, "count": len(prices)}

    return _execute_freelance(request, "freelance.pricing.catalog", handler, db=db, user_id=user_id)


@router.get("/orders")
@limiter.limit("60/minute")
def get_all_orders(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        orders = _run_flow_freelance("freelance_orders_list", {}, db, user_id)
        return {
            "status": "SUCCESS",
            "orders": orders if isinstance(orders, list) else [],
        }
    return _execute_freelance(request, "freelance.orders.list", handler, db=db, user_id=user_id)


@router.get("/clients")
@limiter.limit("60/minute")
def list_clients(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        clients = _run_flow_freelance("freelance_clients_list", {}, db, user_id)
        return {
            "status": "SUCCESS",
            "clients": clients if isinstance(clients, list) else [],
        }
    return _execute_freelance(request, "freelance.clients.list", handler, db=db, user_id=user_id)


@router.get("/clients/{client_id}")
@limiter.limit("60/minute")
def get_client_lineage(
    request: Request,
    client_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_client_lineage(db, client_id, user_id)
    return _execute_freelance(
        request,
        "freelance.clients.lineage",
        handler,
        db=db,
        user_id=user_id,
        input_payload={"client_id": client_id},
    )


@router.post("/intake/from-lead", status_code=201)
@limiter.limit("30/minute")
def intake_from_lead(
    request: Request,
    intake: LeadIntakeRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    idempotency_key = request.headers.get("Idempotency-Key")
    def handler(_ctx):
        _require_idempotency_key(idempotency_key)
        return _do_intake_from_lead(db, intake, user_id, idempotency_key)
    return _execute_freelance(
        request,
        "freelance.intake.from_lead",
        handler,
        db=db,
        user_id=user_id,
        input_payload={**intake.model_dump(), "idempotency_key": idempotency_key},
        success_status_code=201,
    )


@router.get("/intake/actioned-leads")
@limiter.limit("60/minute")
def list_actioned_leads(
    request: Request,
    limit: int = Query(50, description="Max actioned leads to return."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Leads the Search Execution Layer has drafted outreach for — ready to convert."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.freelance.services import intake_service
        leads = intake_service.list_actioned_leads(db, user_id, limit=limit)
        return {"actioned_leads": leads, "count": len(leads)}

    return _execute_freelance(request, "freelance.intake.actioned_leads", handler, db=db, user_id=user_id)


@router.post("/intake/from-action", status_code=201)
@limiter.limit("30/minute")
def intake_from_action(
    request: Request,
    intake: ActionIntakeRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Convert a Search-actioned lead into a client + order (completes lead -> order)."""
    user_id = str(current_user["sub"])
    idempotency_key = request.headers.get("Idempotency-Key")

    def handler(_ctx):
        _require_idempotency_key(idempotency_key)
        from apps.freelance.services import intake_service
        try:
            result = intake_service.convert_actioned_lead(
                db,
                user_id,
                action_id=intake.action_id,
                client_email=intake.client_email,
                service_type=intake.service_type,
                client_name=intake.client_name,
                price=intake.price or 0.0,
                project_details=intake.project_details,
                delivery_type=intake.delivery_type or "manual",
                delivery_config=intake.delivery_config,
                auto_generate_delivery=intake.auto_generate_delivery,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        order = result["order"]
        client = result["client"]
        return {
            "status": "created",
            "action_id": result["action_id"],
            "lead_id": result["lead_id"],
            "order": {
                "id": order.id,
                "service_type": order.service_type,
                "price": order.price,
                "status": order.status,
                "client_email": order.client_email,
            },
            "client": {"id": client.id, "email": client.email},
        }

    return _execute_freelance(
        request,
        "freelance.intake.from_action",
        handler,
        db=db,
        user_id=user_id,
        input_payload={**intake.model_dump(), "idempotency_key": idempotency_key},
        success_status_code=201,
    )


@router.post("/clients/onboard", status_code=201)
@limiter.limit("30/minute")
def onboard_client(
    request: Request,
    intake: LeadIntakeRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Onboard a qualified lead end-to-end (Phase 3): convert lead -> client + order,
    then dispatch delivery generation when requested — one multi-step, observable flow."""
    user_id = str(current_user["sub"])
    idempotency_key = request.headers.get("Idempotency-Key")

    def handler(_ctx):
        _require_idempotency_key(idempotency_key)
        return _do_onboard_client(db, intake, user_id, idempotency_key)

    return _execute_freelance(
        request,
        "freelance.clients.onboard",
        handler,
        db=db,
        user_id=user_id,
        input_payload={**intake.model_dump(), "idempotency_key": idempotency_key},
        success_status_code=201,
    )


@router.post("/orders/{order_id}/fulfill")
@limiter.limit("30/minute")
def fulfill_order(
    request: Request,
    order_id: int,
    body: FulfillOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Fulfill an order end-to-end (Phase 3): attach the deliverable, then refresh
    revenue metrics so they reflect the delivery — one multi-step flow."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        return _do_fulfill_order(db, order_id, body, user_id)

    return _execute_freelance(
        request,
        "freelance.orders.fulfill",
        handler,
        db=db,
        user_id=user_id,
        input_payload={"order_id": order_id, **body.model_dump()},
    )


@router.get("/feedback")
@limiter.limit("60/minute")
def get_all_feedback(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _run_flow_freelance("freelance_feedback_list", {}, db, user_id)
    return _execute_freelance(request, "freelance.feedback.list", handler, db=db, user_id=user_id)


@router.get("/metrics/latest")
@limiter.limit("60/minute")
def get_latest_metrics(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _run_flow_freelance("freelance_metrics_latest", {}, db, user_id)
    return _execute_freelance(request, "freelance.metrics.latest", handler, db=db, user_id=user_id)


@router.post("/metrics/update")
@limiter.limit("30/minute")
def update_metrics(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_update_metrics(db, user_id)
    return _execute_freelance(
        request,
        "freelance.metrics.update",
        handler,
        db=db,
        user_id=user_id,
        input_payload={},
    )


@router.post("/generate/{order_id}")
@limiter.limit("30/minute")
def generate_delivery(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_generate_delivery(db, order_id, user_id)
    return _execute_freelance(
        request,
        "freelance.delivery.generate",
        handler,
        db=db,
        user_id=user_id,
        input_payload={"order_id": order_id},
    )


@router.post("/refund/{order_id}")
@limiter.limit("10/minute")
def refund_order(
    request: Request,
    order_id: int,
    body: RefundRequest | None = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    reason = body.reason if body else None
    idempotency_key = request.headers.get("Idempotency-Key")

    def handler(_ctx):
        _require_idempotency_key(idempotency_key)
        return _do_issue_refund(db, order_id, reason, user_id, idempotency_key)

    result = _execute_freelance(
        request,
        "freelance.refund",
        handler,
        db=db,
        user_id=user_id,
        input_payload={"order_id": order_id, "reason": reason, "idempotency_key": idempotency_key},
        success_status_code=201,
    )
    if isinstance(result, dict):
        result = dict(result)
        idempotency = result.pop("_idempotency", {})
        status_code = 201 if idempotency.get("created", True) else 200
        return JSONResponse(status_code=status_code, content=jsonable_encoder(result))
    return result


@router.post("/subscription/{order_id}/cancel")
@limiter.limit("10/minute")
def cancel_subscription(
    request: Request,
    order_id: int,
    body: SubscriptionCancelRequest | None = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    reason = body.reason if body else None

    def handler(_ctx):
        return _do_cancel_subscription(db, order_id, reason, user_id)

    return _execute_freelance(
        request,
        "freelance.subscription.cancel",
        handler,
        db=db,
        user_id=user_id,
        input_payload={"order_id": order_id},
    )


@router.post("/webhook/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: str | None = Header(None, alias="stripe-signature"),
):
    """
    Receive Stripe webhook events. Public endpoint — no auth.
    Verified via HMAC-SHA256 signature (Stripe-Signature header).
    """
    from AINDY.config import settings
    from apps.freelance.services.freelance_service import verify_stripe_signature
    from apps.freelance.services.idempotency import (
        claim_webhook_event,
        mark_webhook_outcome,
    )
    from apps.freelance.services.webhook_service import handle_stripe_event

    payload_bytes = await request.body()

    webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    # Best-effort peek, for the pipeline's input_payload only. The authoritative parse —
    # and the 400 it can raise — happens inside the handler, so a malformed body is
    # rejected with a reason rather than blowing up before the pipeline exists.
    try:
        _preview = _json.loads(payload_bytes)
    except Exception:
        _preview = {}
    event_type = str((_preview or {}).get("type") or "")
    stripe_event_id = str((_preview or {}).get("id") or "")

    def handler(ctx):
        # Signature and body checks run inside the pipeline. Raised above it they were
        # rewritten as RouteExecutionViolation, so Stripe saw a 500 for a rejected
        # signature — which reads as "retry me" rather than "this delivery is invalid",
        # and 500s are exactly what Stripe retries.
        if webhook_secret:
            if not stripe_signature:
                raise HTTPException(status_code=400, detail="stripe-signature header missing")
            if not verify_stripe_signature(payload_bytes, stripe_signature, webhook_secret):
                raise HTTPException(
                    status_code=400, detail="stripe-signature verification failed"
                )

        try:
            event = _json.loads(payload_bytes)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")

        if not stripe_event_id:
            return {"received": True, "processed": False}

        if not claim_webhook_event(db, stripe_event_id, event_type, payload=event):
            return {"status": "skipped", "reason": "already_processed"}

        try:
            outcome = handle_stripe_event(db, event)
            mark_webhook_outcome(db, stripe_event_id, "fulfilled")
            return {"status": "ok", "outcome": outcome}
        except Exception as exc:
            logger.warning("[stripe] webhook processing failed: %s", exc)
            mark_webhook_outcome(db, stripe_event_id, "failed", error=str(exc))
            return {"status": "failed", "reason": "processing_error"}

    result = await execute_with_pipeline(
        request=request,
        route_name="freelance.webhook.stripe",
        handler=handler,
        input_payload={"event_type": event_type, "event_id": stripe_event_id},
        metadata={"db": db, "source": "freelance"},
        return_result=True,
    )
    if not result.success:
        detail = result.metadata.get("detail") or result.error or "Execution failed"
        raise HTTPException(
            status_code=int(result.metadata.get("status_code", 500)),
            detail=detail,
        )
    data = result.data
    if isinstance(data, dict):
        data = dict(data)
        data.pop("execution_envelope", None)
    return data

