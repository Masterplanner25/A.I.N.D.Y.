"""The Resolution Check's HTTP surface — `RESOLUTION_CHECK_SPEC.md`. Served at `/apps/resolution`.

A check is started here and answered by the scheduled tick (`masterplan_resolution_tick`), a few
answers a minute; the overview shows it filling in.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from AINDY.core.execution_helper import execute_with_pipeline
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user

from apps.masterplan.routes.masterplan_router import _with_execution_envelope

router = APIRouter(prefix="/resolution", tags=["Resolution"])


class StartBody(BaseModel):
    scope: Optional[str] = "core"


async def _run(request: Request, route_name: str, handler, *, db: Session, user_id: str, payload: dict):
    result = await execute_with_pipeline(
        request=request, route_name=route_name, handler=handler, user_id=user_id,
        input_payload=payload, metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.get("")
@limiter.limit("60/minute")
async def resolution_overview_route(request: Request, db: Session = Depends(get_db),
                                    current_user: dict = Depends(get_current_user)):
    """The latest check, answer by answer, and your own self-descriptions side by side."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.resolution_service import resolution_overview
        return resolution_overview(db, user_id)

    return await _run(request, "masterplan.resolution.overview", handler, db=db, user_id=user_id, payload={})


@router.post("/runs")
@limiter.limit("6/minute")
async def start_resolution_run_route(request: Request, body: StartBody, db: Session = Depends(get_db),
                                     current_user: dict = Depends(get_current_user)):
    """Start a check: core (the person, the brand, three projects, three links) or full."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.resolution_service import start_run
        return start_run(db, user_id, body.scope or "core")

    return await _run(request, "masterplan.resolution.start", handler, db=db, user_id=user_id,
                      payload={"scope": body.scope})


@router.get("/runs/{run_id}")
@limiter.limit("60/minute")
async def get_resolution_run_route(request: Request, run_id: str, db: Session = Depends(get_db),
                                   current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.resolution_service import get_run
        return get_run(db, user_id, run_id)

    return await _run(request, "masterplan.resolution.run", handler, db=db, user_id=user_id,
                      payload={"run_id": run_id})
