"""
Search result feedback router — capture implicit/explicit feedback + read the
aggregated per-query outcome weights (Search v4 §8).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline_sync
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user
from apps.search.services.feedback_service import (
    SIGNAL_WEIGHTS,
    get_result_outcome_weights,
    record_feedback,
)

router = APIRouter(prefix="/search", tags=["Search Feedback"])
logger = logging.getLogger(__name__)


class FeedbackRequest(BaseModel):
    query: str
    result_ref: str
    signal: str  # click | dwell | convert | dismiss | thumbs_up | thumbs_down
    history_id: str | None = None


def _execute(request: Request, route_name: str, handler, *, db: Session, user_id: str, input_payload=None):
    result = execute_with_pipeline_sync(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        input_payload=input_payload or {},
        metadata={"db": db, "source": "search_feedback"},
        return_result=True,
    )
    if not result.success:
        detail = result.metadata.get("detail") or result.error or "Execution failed"
        raise HTTPException(status_code=int(result.metadata.get("status_code", 500)), detail=detail)
    data = result.data
    if isinstance(data, dict):
        data = dict(data)
        data.setdefault(
            "execution_envelope",
            to_envelope(
                eu_id=result.metadata.get("eu_id"), trace_id=result.metadata.get("trace_id"),
                status="SUCCESS", output=None, error=None, duration_ms=None, attempt_count=None,
            ),
        )
    return data


@router.post("/feedback")
@limiter.limit("120/minute")
def record_search_feedback(
    request: Request,
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Record implicit (click/dwell/convert/dismiss) or explicit (thumbs_up/thumbs_down)
    feedback on a search result. Idempotent per (user, query, result_ref, signal)."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        # Inside the pipeline: raised before entry, the runtime's route guard cannot
        # tell a deliberate 4xx from a route bypassing the pipeline and rewrites it as
        # RouteExecutionViolation, so the caller got an opaque 500 instead of the reason.
        if (body.signal or "").strip().lower() not in SIGNAL_WEIGHTS:
            raise HTTPException(
                status_code=422,
                detail=f"unknown feedback signal '{body.signal}'; expected one of {sorted(SIGNAL_WEIGHTS)}",
            )
        return record_feedback(
            db, user_id=user_id, query=body.query, result_ref=body.result_ref,
            signal=body.signal, history_id=body.history_id,
        )

    return _execute(request, "search.feedback.record", handler, db=db, user_id=user_id, input_payload=body.model_dump())


@router.get("/feedback/weights")
@limiter.limit("60/minute")
def get_search_feedback_weights(
    request: Request,
    query: str = Query(..., description="The query whose per-result outcome weights to read."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Aggregated per-result outcome weights for a query (implicit + explicit blended)."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        weights = get_result_outcome_weights(db, user_id, query)
        return {"query": query, "weights": weights, "count": len(weights)}

    return _execute(request, "search.feedback.weights", handler, db=db, user_id=user_id)
