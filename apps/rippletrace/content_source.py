"""Recurring supply of published content for rippletrace.

A drop point is a thing you published somewhere else. Until now the only way to get
one into the system was to type it, which is why ``drop_points`` was empty: the
learning chain needs ~8 pings on each of 3 drop points before ``build_strategies``
emits anything, and nobody hand-enters their way to that.

A ``ContentSourceDB`` row is a feed (RSS/Atom) the user has published to — Substack,
Medium, Ghost, WordPress, a YouTube channel. One registration turns into a permanent
supply: every future post ingests itself on the poll job. Platforms without feeds
(LinkedIn, X) stay one-URL-at-a-time, which is why page ingestion exists alongside
this and does *not* create a source row.

``etag``/``last_modified`` are stored so polling can issue a conditional GET and take
the 304 path; a feed that has not changed costs one cheap request.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentSourceDB(Base):
    __tablename__ = "ripple_content_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "feed_url", name="uq_ripple_content_sources_user_feed"),
    )

    id = Column(String(36), primary_key=True, index=True)
    # Mirrors DropPointDB's ownership column so a source and the drop points it
    # produces are scoped the same way.
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    feed_url = Column(String, nullable=False, index=True)
    site_url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    platform = Column(String, nullable=True)
    # "feed" today. Reserved so a sitemap or platform-API source can be added without
    # a second table.
    kind = Column(String(16), nullable=False, default="feed")

    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    last_polled_at = Column(DateTime(timezone=True), nullable=True)
    # ok | unchanged | error — the poll job never raises, so this column is how a
    # broken feed becomes visible instead of silently going quiet.
    last_status = Column(String(32), nullable=True)
    last_error = Column(Text, nullable=True)
    last_entry_count = Column(Integer, nullable=True)
    ingested_count = Column(Integer, nullable=False, default=0)

    etag = Column(String, nullable=True)
    last_modified = Column(String, nullable=True)
