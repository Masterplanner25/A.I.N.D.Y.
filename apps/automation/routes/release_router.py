"""The release handoff's HTTP surface — `RELEASE_HANDOFF_SPEC.md` phase 1. Served at `/apps/releases`.

A handoff is recorded here; the scheduled watcher (`release_handoff_watch`) follows the run from there,
once a minute. Refusals are `{error: "release_refused", message}`.
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user

router = APIRouter(prefix="/releases", tags=["Releases"])


class HandoffBody(BaseModel):
    repo: str = "Masterplanner25/aindy-runtime"
    tag: str


def _with_execution_envelope(payload):
    envelope = to_envelope(eu_id=None, trace_id=None, status="SUCCESS", output=None, error=None,
                           duration_ms=None, attempt_count=1)
    if hasattr(payload, "status_code") and hasattr(payload, "body"):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        result = dict(data) if isinstance(data, dict) else dict(payload)
        result.setdefault("execution_envelope", envelope)
        return result
    return {"data": payload, "execution_envelope": envelope}


async def _run(request: Request, route_name: str, handler, *, db: Session, user_id: str, payload: dict):
    result = await execute_with_pipeline(
        request=request, route_name=route_name, handler=handler, user_id=user_id,
        input_payload=payload, metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.get("")
@limiter.limit("60/minute")
async def list_releases_route(request: Request, active: bool = False, limit: int = 10,
                              db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Your handoffs, newest first; `active=true` for the ones still being followed."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.automation.services.release_handoff_service import list_handoffs
        return list_handoffs(db, user_id, active_only=active, limit=limit)

    return await _run(request, "automation.release.list", handler, db=db, user_id=user_id,
                      payload={"active": active, "limit": limit})


@router.post("")
@limiter.limit("10/minute")
async def hand_off_release_route(request: Request, body: HandoffBody, db: Session = Depends(get_db),
                                 current_user: dict = Depends(get_current_user)):
    """Hand a tagged release off: A.I.N.D.Y. finds its publish run and follows it to the end."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.automation.services.release_handoff_service import start_handoff
        return start_handoff(db, user_id, body.repo, body.tag)

    return await _run(request, "automation.release.handoff", handler, db=db, user_id=user_id,
                      payload={"repo": body.repo, "tag": body.tag})
