# /services/network_bridge_services.py
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from AINDY.kernel.syscall_dispatcher import dispatch_syscall

logger = logging.getLogger(__name__)

def register_author(db: Session, name: str, platform: str, notes: str | None = None, user_id: str | uuid.UUID | None = None):
    """
    Registers or updates an author record in the database.
    """
    from apps.authorship.public import register_author as register_author_public

    return register_author_public(
        db,
        name=name,
        platform=platform,
        notes=notes,
        user_id=user_id,
    )


def connect_external_author(
    db: Session,
    *,
    author_name: str,
    platform: str,
    connection_type: str,
    notes: str | None,
    user_id: str | uuid.UUID | None = None,
) -> dict:
    """
    Register the author, log a ripple event, save a metric, and commit.

    Returns the result dict for the route handler.
    All DB work (including the final commit) is owned here.
    """
    from datetime import datetime

    author = register_author(db=db, name=author_name, platform=platform, notes=notes)

    ripple_event = {
        "ping_type": connection_type,
        "source_platform": platform,
        "summary": f"{author_name} connected via {platform}",
        "notes": notes or "",
        "drop_point_id": "bridge",
    }
    normalized_user_id = str(user_id) if user_id is not None else None
    dispatch_syscall(
        "sys.v1.rippletrace.log_ripple_event",
        {
            "event_type": connection_type,
            "user_id": normalized_user_id,
            "source": platform,
            "data": ripple_event,
        },
        db=db,
        user_id=normalized_user_id,
        capability="rippletrace.write",
    )

    metric_name = f"UserEvent::{platform}"
    dispatch_syscall(
        "sys.v1.analytics.save_calculation",
        {"metric_name": metric_name, "value": 1, "user_id": normalized_user_id},
        db=db,
        user_id=normalized_user_id,
        capability="analytics.write",
    )

    db.commit()

    return {
        "status": "connected",
        "author_id": author["id"],
        "platform": platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


SIGN_IN_PLATFORM = "AINDY"


def handle_sign_in(context: dict):
    """Record a sign-in: seed the author, log the ripple, count the event.

    Runs on the runtime's ``auth.login.completed`` event. Three things come out of one
    sign-in, which is what this domain was always for:

    * **an author row** — the person entering the system, so ``authorship`` has a
      registry with something in it rather than a table that has never held a row
    * **a rippletrace ping** — a system-generated signal alongside the content echoes,
      giving that domain a second, non-content supply
    * **an analytics counter** (``UserEvent::AINDY``) — the countable "how many times
      has this person actually used the app", which nothing produced before

    **Owns its own session.** The internal event dispatcher passes only
    ``{event_id, event_type, payload, user_id, trace_id, source}`` — there is no ``db``
    on the event, unlike the registry-bus handlers that receive one. Reading
    ``context["db"]`` here silently no-ops.

    Best-effort by contract: a sign-in must never fail because a downstream domain is
    degraded. Everything is swallowed — the user is already authenticated by the time
    this runs, so raising here would break login for a bookkeeping write.
    """
    from AINDY.db.database import SessionLocal

    user_id = context.get("user_id")
    if not user_id:
        logger.debug("[network_bridge] sign-in event without user_id; skipping")
        return None

    payload = context.get("payload") or {}
    email = str(payload.get("email") or "").strip()
    # The email is the only identifying field on the login event; fall back to the id so
    # an author row is still created if it is ever absent.
    name = email or f"user:{user_id}"

    db = SessionLocal()
    try:
        result = connect_external_author(
            db,
            author_name=name,
            platform=SIGN_IN_PLATFORM,
            connection_type="sign_in",
            notes="Signed in",
            user_id=user_id,
        )
        _record_bridge_user_event(db, name)
        return result
    except Exception as exc:
        db.rollback()
        logger.warning("[network_bridge] sign-in capture failed for %s: %s", user_id, exc)
        return None
    finally:
        db.close()


def _record_bridge_user_event(db: Session, name: str) -> None:
    """Write the system-origin audit row the social feed surfaces.

    ``bridge_user_events`` is owned by automation and read by
    ``social/bridge_feed_service`` into the feed's ``events`` channel, gated to
    system-origin rows. Its only writer used to be ``POST /apps/bridge/user_event`` —
    an endpoint with no callers — so the table was empty and that channel was
    structurally dead. A sign-in is precisely the system-origin event it was built to
    carry.

    Separately committed and never fatal: the author, ping and metric are already
    persisted by this point, and an audit row is not worth losing them over.
    """
    from datetime import datetime as _dt

    from apps.automation.public import create_bridge_user_event

    occurred_at = _dt.now(timezone.utc)
    try:
        create_bridge_user_event(
            db,
            user=name,
            origin="system",
            raw_timestamp=occurred_at.isoformat(),
            occurred_at=occurred_at,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("[network_bridge] bridge user event write failed: %s", exc)


def list_authors(db: Session, platform: str | None = None, limit: int = 100):
    from apps.authorship.public import list_authors as list_authors_public

    return list_authors_public(db, platform=platform, limit=limit)

