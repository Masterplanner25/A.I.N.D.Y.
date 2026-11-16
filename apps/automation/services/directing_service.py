"""Storing directing events: `DIRECTING_TIME_SPEC.md` §3.

Idempotent on `(user_id, source, source_event_id)`. A repeat is counted as a duplicate, and it moves `agent_until`
on when the new value is later, so the backfill can complete the reading the hook started.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

MAX_BATCH = 500


def _parse(stamp) -> Optional[datetime]:
    if isinstance(stamp, datetime):
        value = stamp
    elif isinstance(stamp, str) and stamp:
        try:
            value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def ingest_events(db: Session, user_id: str, events: Iterable[dict]) -> dict:
    """Store new events for `user_id`; the caller is always the authenticated user, never the payload."""
    from apps.automation.directing import DirectingEvent

    owner = uuid.UUID(str(user_id))
    rows: dict[tuple[str, str], dict] = {}
    rejected = 0
    for event in events:
        occurred = _parse(event.get("occurred_at"))
        key = (str(event.get("source") or ""), str(event.get("source_event_id") or ""))
        if occurred is None or not all(key) or not event.get("agent_session_id"):
            rejected += 1
            continue
        until = _parse(event.get("agent_until"))
        rows[key] = {
            "source": key[0][:32],
            "project": str(event.get("project") or "")[:255],
            "agent_session_id": str(event["agent_session_id"])[:64],
            "source_event_id": key[1][:64],
            "occurred_at": occurred,
            "agent_until": until if until and until >= occurred else None,
        }

    accepted = duplicates = extended = 0
    by_source: dict[str, list[str]] = {}
    for source, event_id in rows:
        by_source.setdefault(source, []).append(event_id)
    existing: dict[tuple[str, str], DirectingEvent] = {}
    for source, ids in by_source.items():
        for row in (
            db.query(DirectingEvent)
            .filter(DirectingEvent.user_id == owner, DirectingEvent.source == source,
                    DirectingEvent.source_event_id.in_(ids))
            .all()
        ):
            existing[(row.source, row.source_event_id)] = row

    for key, values in rows.items():
        row = existing.get(key)
        if row is None:
            db.add(DirectingEvent(user_id=owner, **values))
            accepted += 1
            continue
        duplicates += 1
        until = values["agent_until"]
        current = row.agent_until
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if until is not None and (current is None or until > current):
            row.agent_until = until
            extended += 1
    db.flush()
    return {"accepted": accepted, "duplicates": duplicates, "extended": extended, "rejected": rejected}
