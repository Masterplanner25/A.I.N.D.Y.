from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline_sync
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user


router = APIRouter(prefix="/goals", tags=["Goals"])


def _execute_goals(request: Request, route_name: str, handler, *, db: Session, user_id: str, input_payload=None, success_status_code: int = 200):
    result = execute_with_pipeline_sync(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        input_payload=input_payload or {},
        metadata={"db": db, "source": "goals_router"},
        success_status_code=success_status_code,
        return_result=True,
    )
    if not result.success:
        detail = result.metadata.get("detail") or result.error or "Execution failed"
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


class GoalCreateRequest(BaseModel):
    name: str
    description: str | None = None
    goal_type: str = "strategic"
    priority: float = 0.5
    status: str = "active"
    success_metric: dict = Field(default_factory=dict)
    # GOALS_LAYER_SPEC §5: a goal the person states. Measured by the objectives it links to, or declared.
    objective_ids: list[str] = Field(default_factory=list)


def _do_create_goal(db: Session, body: GoalCreateRequest, user_id: str):
    from apps._shared.flow import run_flow_or_raise

    result = run_flow_or_raise(
        "goal_create",
        {
            "name": body.name,
            "description": body.description,
            "goal_type": body.goal_type,
            "priority": body.priority,
            "status": body.status,
            "success_metric": body.success_metric,
            "objective_ids": body.objective_ids,
        },
        db=db,
        user_id=user_id,
    )
    return result.get("data")


@router.get("")
@limiter.limit("60/minute")
def list_goals(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise("goals_list", {}, db=db, user_id=user_id)
        return result.get("data")
    return _execute_goals(request, "goals.list", handler, db=db, user_id=user_id)


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_goal_route(
    request: Request,
    body: GoalCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _do_create_goal(db, body, user_id)
    return _execute_goals(
        request,
        "goals.create",
        handler,
        db=db,
        user_id=user_id,
        input_payload=body.model_dump(),
        success_status_code=status.HTTP_201_CREATED,
    )


@router.get("/state")
@limiter.limit("60/minute")
def list_goal_state(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise("goals_state", {}, db=db, user_id=user_id)
        return result.get("data")
    return _execute_goals(request, "goals.state", handler, db=db, user_id=user_id)


# ── GOALS_LAYER_SPEC phase B: proposals and the person's say (decided 2026-11-09) ──────────────────────────────


class GoalEdit(BaseModel):
    name: str | None = None
    description: str | None = None
    priority: float | None = Field(default=None, ge=0.0, le=1.0)
    objective_ids: list[str] | None = None


class GoalUpdate(GoalEdit):
    status: str | None = None  # "completed" marks a declared goal done; "active" reopens one


def _goal_call(fn):
    """Map the seeding service's refusals onto statuses: not yours or missing → 404, not allowed → 422."""
    try:
        return fn()
    except LookupError:
        raise HTTPException(status_code=404, detail="Goal not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/overview")
@limiter.limit("60/minute")
def goals_overview_route(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Proposals from the active plan (made once), the person's goals, and the objectives they can link to."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.masterplan.services.goal_seeding import goals_overview

        return goals_overview(db, user_id)

    return _execute_goals(request, "goals.overview", handler, db=db, user_id=user_id)


@router.post("/{goal_id}/confirm")
@limiter.limit("30/minute")
def confirm_goal_route(
    request: Request,
    goal_id: str,
    body: GoalEdit | None = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Accept a proposed goal, with any edits. It becomes active and is measured from now on."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.masterplan.services.goal_seeding import confirm_goal

        edits = body.model_dump(exclude_none=True) if body else {}
        return _goal_call(lambda: confirm_goal(db, user_id, goal_id, edits))

    return _execute_goals(request, "goals.confirm", handler, db=db, user_id=user_id)


@router.post("/{goal_id}/drop")
@limiter.limit("30/minute")
def drop_goal_route(
    request: Request,
    goal_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Drop a proposal or a goal. A dropped proposal is never proposed again."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.masterplan.services.goal_seeding import drop_goal

        return _goal_call(lambda: drop_goal(db, user_id, goal_id))

    return _execute_goals(request, "goals.drop", handler, db=db, user_id=user_id)


@router.patch("/{goal_id}")
@limiter.limit("30/minute")
def update_goal_route(
    request: Request,
    goal_id: str,
    body: GoalUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Edit a goal: its name, description, priority or objective links; `status: completed` marks a declared goal done."""
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps.masterplan.services.goal_seeding import update_goal

        return _goal_call(lambda: update_goal(db, user_id, goal_id, body.model_dump(exclude_none=True)))

    return _execute_goals(request, "goals.update", handler, db=db, user_id=user_id)

