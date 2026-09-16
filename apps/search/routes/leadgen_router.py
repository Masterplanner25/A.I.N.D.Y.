"""
LEAD GENERATION ROUTER
------------------------------------
Endpoint Layer for: B2B Lead Generation via AI Search Optimization
Purpose: Exposes API routes to trigger A.I.N.D.Y.'s autonomous
lead discovery and scoring engine.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline_sync
from AINDY.db.database import get_db
from apps.search.schemas.leadgen_schema import LeadGenItem
from apps.search.routes._route_helpers import (
    _ai_provider_unavailable_response,
    _extract_flow_error,
    _is_circuit_open_detail,
)
from AINDY.services.auth_service import get_current_user
from AINDY.platform_layer.rate_limiter import limiter
from apps.search.schemas.search_schema import enrich_lead_row, leadgen_to_search_response
from apps.search.services.search_service import build_learning_context, get_cached_search_result

router = APIRouter(prefix="/leadgen", tags=["Lead Generation"])
legacy_router = APIRouter(tags=["Lead Generation"])
logger = logging.getLogger(__name__)

def _execute_leadgen(request: Request, route_name: str, handler, *, db: Session, user_id: str, input_payload=None):
    result = execute_with_pipeline_sync(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        input_payload=input_payload or {},
        metadata={"db": db, "source": "leadgen"},
        return_result=True,
    )
    if not result.success:
        detail = result.metadata.get("detail") or result.error or "Execution failed"
        if _is_circuit_open_detail(detail):
            return _ai_provider_unavailable_response(detail)
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


def _do_generate_b2b_leads(db: Session, user_id: str, query: str):
    start = time.perf_counter()

    # Fast path: return cached results without running the flow
    cached = get_cached_search_result(
        db=db,
        user_id=user_id,
        query=query,
        search_type="leadgen",
    )
    if cached:
        cached_results = cached.get("results") or []
        results_payload = [
            enrich_lead_row(LeadGenItem(**row).model_dump()) for row in cached_results
        ]
        payload = {
            "query": query,
            "count": len(cached_results),
            "results": results_payload,
            "search_type": "leadgen",
            "learning_context": cached.get("learning_context")
            or build_learning_context(cached, default_search_type="leadgen"),
            "_execution_meta": {"cached": True, "count": len(cached_results)},
        }
        payload["search_score"] = leadgen_to_search_response(payload).search_score
        return payload

    from AINDY.runtime.flow_engine import run_flow

    result = run_flow(
        "leadgen_search",
        {"query": query},
        db=db,
        user_id=user_id,
    )
    status = str(result.get("status") or "").upper()
    if status != "SUCCESS":
        error = _extract_flow_error(result) or "LeadGen flow failed"
        if _is_circuit_open_detail(error):
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "ai_provider_unavailable",
                    "message": "An AI provider is temporarily unavailable. Please retry in a moment.",
                    "detail": str(error),
                    "retryable": True,
                },
            )
        raise RuntimeError(str(error))

    flow_data = result.get("data") or []
    if isinstance(flow_data, dict):
        search_results = flow_data.get("search_results") or []
    else:
        search_results = flow_data
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info("LeadGen generated %s results in %.2fms", len(search_results), duration_ms)
    results_payload = [
        enrich_lead_row(LeadGenItem(**item).model_dump()) for item in search_results
    ]
    payload = {
        "query": query,
        "count": len(search_results),
        "results": results_payload,
        "search_type": "leadgen",
        "_execution_meta": {
            "count": len(search_results),
            "duration_ms": round(duration_ms, 2),
        },
    }
    payload["search_score"] = leadgen_to_search_response(payload).search_score
    return payload


@router.post("/")
@limiter.limit("10/minute")
def generate_b2b_leads(
    request: Request,
    query: str = Query(..., description="Search intent or keyword for AI lead discovery"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_generate_b2b_leads(db, user_id, query)
    return _execute_leadgen(
        request,
        "leadgen.generate",
        handler,
        db=db,
        user_id=user_id,
        input_payload={"query": query},
    )


@router.get("/search")
@limiter.limit("60/minute")
def preview_lead_search(
    request: Request,
    query: str = Query(..., description="Search intent or keyword for AI lead discovery"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        from apps.search.services.search_service import search_leads
        return search_leads(query=query, db=db, user_id=user_id)
    return _execute_leadgen(request, "leadgen.search", handler, db=db, user_id=user_id, input_payload={"query": query})


@router.get("/")
@limiter.limit("60/minute")
def list_all_leads(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.search.services.leadgen_service import list_leads
        return list_leads(db, user_id=user_id)

    return _execute_leadgen(request, "leadgen.list", handler, db=db, user_id=user_id)


class RevertActionRequest(BaseModel):
    action_id: int


class LeadContactRequest(BaseModel):
    contact_email: str | None = None  # None or "" clears it


@router.patch("/leads/{lead_id}/contact")
@limiter.limit("30/minute")
def set_lead_contact_route(
    request: Request,
    lead_id: int,
    body: LeadContactRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Enter (or clear) the recipient for a lead by hand. The `email` channel sends only to
    leads that have one; discovery never sets it."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.search.services.leadgen_service import set_lead_contact
        try:
            lead = set_lead_contact(db, user_id=user_id, lead_id=lead_id, contact_email=body.contact_email)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error": "invalid_contact", "message": str(exc)})
        if lead is None:
            raise HTTPException(status_code=404, detail={"error": "lead_not_found", "message": f"lead {lead_id} not found"})
        return lead

    return _execute_leadgen(
        request, "leadgen.contact.set", handler, db=db, user_id=user_id,
        input_payload={"lead_id": lead_id, "has_contact": bool((body.contact_email or "").strip())},
    )


@router.post("/execute")
@limiter.limit("10/minute")
def execute_lead_actions(
    request: Request,
    apply: bool = Query(False, description="Persist actions. Default false = dry-run preview."),
    channel: str = Query("draft", description="draft | email | handoff. 'email' sends only with AINDY_SEARCH_OUTREACH_SEND on, and only to leads with a hand-entered contact_email."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Act on scored leads: draft outreach for qualified leads, gated and revertible; the email
    channel delivers it (gate on, recipient entered) and a sent action is not revertible."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.search.services.lead_execution_service import LeadExecutionService
        svc = LeadExecutionService(db=db, user_id=user_id)
        if apply:
            return svc.execute(channel=channel, trigger="manual")
        return {"dry_run": True, **svc.plan()}

    return _execute_leadgen(
        request, "leadgen.execute", handler, db=db, user_id=user_id,
        input_payload={"apply": apply, "channel": channel},
    )


@router.post("/execute/revert")
@limiter.limit("15/minute")
def revert_lead_action(
    request: Request,
    body: RevertActionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Revert a lead action so its lead becomes eligible for action again."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.search.services.lead_execution_service import LeadExecutionService
        return LeadExecutionService(db=db, user_id=user_id).revert(body.action_id)

    return _execute_leadgen(
        request, "leadgen.execute.revert", handler, db=db, user_id=user_id,
        input_payload=body.model_dump(),
    )


@router.get("/actions")
@limiter.limit("60/minute")
def list_lead_actions(
    request: Request,
    limit: int = Query(20, description="Max actions to return."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List this user's lead actions (drafts, decisions, status, revert state)."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.search.services.lead_execution_service import LeadExecutionService
        actions = LeadExecutionService(db=db, user_id=user_id).history(limit=limit)
        return {"actions": actions, "count": len(actions)}

    return _execute_leadgen(request, "leadgen.actions", handler, db=db, user_id=user_id)


for _route in list(router.routes):
    _path = getattr(_route, "path", None)
    if not _path or not _path.startswith("/leadgen"):
        continue
    legacy_router.add_api_route(
        _path.removeprefix("/leadgen") or "/",
        _route.endpoint,
        methods=list(_route.methods or []),
        name=f"legacy_{_route.name}",
        include_in_schema=False,
    )


