"""Directing time's routes: `DIRECTING_TIME_SPEC.md` §3 (ingest) and §4 (reads). Served at `/apps/directing`.

The caller is the authenticated user; nothing in the payload names a user (DEC-103). The body is closed
(`extra="forbid"`), so a client that tried to send a prompt's text would be refused, not stored (§6).

**The key (decision 6, FR-70):** the hook posts with the person's watcher key. Runtime 2.37.0's `get_activity_caller`
(DEC-133) admits a session, a key holding `watcher.signals` (a watcher-only key included) or `platform.admin`; any other
platform key is a 403 and the shared `X-API-Key` a 401, since it names no user. Never add `enforce_api_key_scope` here:
it resolves through `get_current_user`, which refuses a watcher-only key.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_activity_caller, get_current_user

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


def _directing_caller(current_user: dict = Depends(get_activity_caller)) -> dict:
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


# ── reads (§4): a signed-in session; the watcher key only writes ─────────────────────


def _bound(value: Optional[str], name: str) -> Optional[datetime]:
    """A `from`/`to` bound: a date (its UTC midnight) or an ISO datetime."""
    if not value:
        return None
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail={"message": f"`{name}` takes a date (YYYY-MM-DD) or an ISO time."})
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.get("/sessions")
@limiter.limit("60/minute")
async def list_directing_sessions_route(request: Request, from_: Optional[str] = Query(None, alias="from"),
                                        to: Optional[str] = None, db: Session = Depends(get_db),
                                        current_user: dict = Depends(get_current_user)):
    """Directing sessions that start in `[from, to)`: start, end, minutes, prompts, projects, sources. Default the
    last 7 days; at most 92."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.automation.services import directing_read

        end = _bound(to, "to") or datetime.now(timezone.utc)
        start = _bound(from_, "from") or end - timedelta(days=7)
        if start >= end or end - start > timedelta(days=directing_read.MAX_RANGE_DAYS):
            raise HTTPException(status_code=422, detail={
                "message": f"`from` must come before `to`, at most {directing_read.MAX_RANGE_DAYS} days apart."})
        sessions = directing_read.sessions_between(db, user_id, start, end)
        return {"from": start.isoformat(), "to": end.isoformat(),
                "gap_minutes": int(directing_read.GAP.total_seconds() // 60),
                "sessions": [s.as_dict() for s in sessions]}

    result = await execute_with_pipeline(
        request=request, route_name="automation.directing.sessions", handler=handler, user_id=user_id,
        input_payload={"from": from_, "to": to}, metadata={"db": db},
    )
    return _with_execution_envelope(result)


@router.get("/summary")
@limiter.limit("60/minute")
async def directing_summary_route(request: Request, days: int = Query(7, ge=1, le=90), tz: Optional[str] = None,
                                  db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Directing minutes per day beside the watcher's tracked minutes, over the last `days` local days (`tz`, an IANA
    name; default UTC). `in_score` is always false: nothing in the score reads this (decision 5)."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.automation.services import directing_read

        try:
            zone = directing_read.resolve_zone(tz)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"message": str(exc)})
        return directing_read.summary(db, user_id, days, zone)

    result = await execute_with_pipeline(
        request=request, route_name="automation.directing.summary", handler=handler, user_id=user_id,
        input_payload={"days": days, "tz": tz}, metadata={"db": db},
    )
    return _with_execution_envelope(result)
