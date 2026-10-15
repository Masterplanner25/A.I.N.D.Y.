"""A release handed off to A.I.N.D.Y. — `RELEASE_HANDOFF_SPEC.md` §4.

One row per handoff: the repository and tag the owner gave it, the `publish.yml` run it found, and how
far that run has got. `stage` only moves forward, and only the watcher moves it
(`release_handoff_service.release_handoff_watch`), from facts it reads from GitHub each tick.
"""
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base

# §3, in order. `failed` can follow any of the others; nothing follows `done` or `failed`.
RELEASE_STAGES = ("requested", "running", "at_gate", "approved", "published", "done")
RELEASE_TERMINAL = ("done", "failed")


class ReleaseHandoff(Base):
    __tablename__ = "release_handoffs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    repo = Column(String(200), nullable=False)
    tag = Column(String(64), nullable=False)
    version = Column(String(64), nullable=False)
    # GitHub run ids passed 2^31 long ago; kept as text, never as arithmetic.
    run_id = Column(String(32), nullable=True)
    run_url = Column(Text, nullable=True)
    stage = Column(String(16), nullable=False, index=True)
    stage_at = Column(DateTime(timezone=True), nullable=False)
    #: [{stage, at, detail}] — one entry per transition, the GitHub fact behind it in `detail`.
    history = Column(JSON, nullable=False)
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    #: {reason, job, conclusion, url} when stage is `failed`.
    failure = Column(JSON, nullable=True)
    #: {stage: {success, route, error, at}} — one notification per stage, never repeated.
    notified = Column(JSON, nullable=True)
    task_id = Column(String(32), nullable=True)
    task_name = Column(String(200), nullable=True)
    adoption_task_id = Column(String(32), nullable=True)
    memory_node_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
