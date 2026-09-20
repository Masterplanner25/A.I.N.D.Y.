from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional, Literal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from AINDY.core.execution_helper import execute_with_pipeline

from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user


router = APIRouter(prefix="/scores", tags=["Infinity Score"])


# Compatibility note: manual score recalculation is orchestrated via infinity_orchestrator.


class FeedbackRequest(BaseModel):
    source_type: Literal["arm", "agent", "manual"]
    source_id: Optional[str] = None
    feedback_value: int = Field(..., ge=-1, le=1)
    feedback_text: Optional[str] = None
    loop_adjustment_id: Optional[str] = None


def _latest_adjustment_payload(user_id: str, db: Session):
    from AINDY.platform_layer.registry import get_job

    latest_adjustment_payload = get_job("analytics.latest_adjustment_payload")
    if not callable(latest_adjustment_payload):
        return None
    return latest_adjustment_payload(user_id, db)


# ------------------------------
# GET SCORE
# ------------------------------
@router.get("/me")
@limiter.limit("60/minute")
async def get_my_score(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    def handler(ctx):
        from apps._shared.flow import run_flow_or_raise

        result = run_flow_or_raise("score_get", {}, db=db, user_id=str(current_user["sub"]))
        data = result.get("data") or {}
        if isinstance(data, dict) and not data.get("latest_adjustment"):
            data["latest_adjustment"] = _latest_adjustment_payload(
                str(current_user["sub"]),
                db,
            )
        return data

    return await execute_with_pipeline(
        request,
        "scores_get_me",
        handler,
        user_id=str(current_user["sub"]),
        metadata={"db": db},
    )


# ------------------------------
# RECALCULATE
# ------------------------------
@router.post("/me/recalculate")
@limiter.limit("30/minute")
async def recalculate_my_score(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    def handler(ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise(
            "score_recalculate",
            {},
            db=db,
            user_id=str(current_user["sub"]),
        )
        return result.get("data")

    result = await execute_with_pipeline(
        request,
        "scores_recalculate",
        handler,
        user_id=str(current_user["sub"]),
        metadata={"db": db},
    )
    return result


# ------------------------------
# HISTORY
# ------------------------------
@router.get("/me/history")
@limiter.limit("60/minute")
async def get_score_history(
    request: Request,
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    def handler(ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise("score_history", {"limit": limit}, db=db, user_id=str(current_user["sub"]))
        return result.get("data")

    return await execute_with_pipeline(
        request,
        "scores_history",
        handler,
        user_id=str(current_user["sub"]),
        metadata={"db": db},
    )


# ------------------------------
# FEEDBACK
# ------------------------------
@router.post("/feedback")
@limiter.limit("30/minute")
async def record_score_feedback(
    request: Request,
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    def handler(ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise(
            "score_feedback",
            {
                "source_type": body.source_type,
                "source_id": body.source_id,
                "feedback_value": body.feedback_value,
                "feedback_text": body.feedback_text,
                "loop_adjustment_id": body.loop_adjustment_id,
            },
            db=db,
            user_id=str(current_user["sub"]),
        )
        return result.get("data")

    result = await execute_with_pipeline(
        request,
        "scores_feedback",
        handler,
        user_id=str(current_user["sub"]),
        metadata={"db": db},
    )
    return result


@router.get("/feedback")
@limiter.limit("60/minute")
async def get_score_feedback(
    request: Request,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    def handler(ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise("score_feedback_list", {"limit": limit}, db=db, user_id=str(current_user["sub"]))
        return result.get("data")

    return await execute_with_pipeline(
        request,
        "scores_feedback_list",
        handler,
        user_id=str(current_user["sub"]),
        metadata={"db": db},
    )
