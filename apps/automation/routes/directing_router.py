"""Directing time's ingest route: `DIRECTING_TIME_SPEC.md` §3. Served at `/apps/directing`.

The caller is the authenticated user; nothing in the payload names a user (DEC-103). The body is closed
(`extra="forbid"`), so a client that tried to send a prompt's text would be refused, not stored (§6).

**The key (decision 6, FR-70):** the hook is meant to use the person's watcher key. The runtime admits a watcher-only
key on its own `/watcher` routes and no others, and offers app routes no public way to opt in, so for now this route
takes what `get_current_user` takes. A session works, and so does any non-watcher platform key. When FR-70 ships,
`_directing_caller` is the one seam to change.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user

from apps.automation.services.directing_service import MAX_BATCH

router = APIRouter(prefix="/directing", tags=["Directing"])


class DirectingEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    project: str = Field(default="", max_length=255)
    agent_session_id: str = Field(min_length=1, max_length=64)
    source_event_id: str = Field(min_length=1, max_length=64)
    occurred_at: datetime
    agent_until: Optional[datetime] = None


class DirectingBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[DirectingEventIn] = Field(max_length=MAX_BATCH)


def _directing_caller(current_user: dict = Depends(get_current_user)) -> dict:
    return current_user


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


@router.post("/events")
@limiter.limit("120/minute")
async def ingest_directing_events_route(request: Request, body: DirectingBatch, db: Session = Depends(get_db),
                                       current_user: dict = Depends(_directing_caller)):
    """Store prompts the person sent an agent: times and ids, never text. Idempotent; answers the counts."""
    user_id = str(current_user["sub"])
    events = [event.model_dump() for event in body.events]

    def handler(ctx):
        from apps.automation.services.directing_service import ingest_events
        return ingest_events(db, user_id, events)

    result = await execute_with_pipeline(
        request=request, route_name="automation.directing.ingest", handler=handler, user_id=user_id,
        input_payload={"events": len(events)}, metadata={"db": db},
    )
    return _with_execution_envelope(result)
