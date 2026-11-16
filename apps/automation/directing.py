"""A prompt the person sent an agent: `DIRECTING_TIME_SPEC.md` §2.

One row per typed prompt. Times, ids and the project folder only: **never the prompt's text** (decision 3).
`(user_id, source, source_event_id)` is unique, which makes the hook and the backfill safe to overlap.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class DirectingEvent(Base):
    __tablename__ = "directing_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    project = Column(String(255), nullable=False)
    agent_session_id = Column(String(64), nullable=False)
    source_event_id = Column(String(64), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    # The end of the agent's work on this prompt (decision 2); moves on as later lines arrive.
    agent_until = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_event_id", name="uq_directing_events_source_event"),
        Index("ix_directing_events_user_occurred", "user_id", "occurred_at"),
    )
