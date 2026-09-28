"""Works — what the owner has made, how the works relate, and which objectives they serve.

`WORK_MODEL_SPEC.md` §3. A Work holds INTENT (what it is, the owner's role, its lifecycle, what it
serves). It never holds measurement: a series' performance is computed on demand from its drop
points (`GET /containers/performance`), and a Work links to that rather than copying numbers that
move whenever a ping lands (`TITLE_AS_CONTAINER_SPEC` §4b).

Everything here is declared by the owner or proposed-then-confirmed (§4). Nothing is inferred into
these tables silently: the house rule since phase advance, worth, containers and strategy
conclusions.
"""
import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base

# ── Vocabularies (closed, validated in the service) ─────────────────────────────────────────

WORK_KINDS = ("project", "product", "series", "practice", "publication", "other")
WORK_ROLES = ("creator", "author", "maintainer", "contributor")
WORK_STATUSES = ("active", "finished", "paused", "planned")
WORK_PROVENANCE = ("declared", "confirmed")

# §3.2 — six verbs, on purpose. A free-text relation is a sentence nothing can reason over.
WORK_RELATIONS = {
    "built_on": "runs on / depends on",
    "executes": "is the language or engine that runs",
    "demonstrates": "is a working implementation of",
    "part_of": "is a component of",
    "informs": "shaped the ideas of",
    "precedes": "came before, and is continued by",
}


class Work(Base):
    __tablename__ = "works"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    kind = Column(String(24), nullable=False)
    # Required, in the owner's words: a work without one is a string with an id (§3.1).
    summary = Column(Text, nullable=False)
    role = Column(String(24), nullable=False)
    status = Column(String(16), nullable=False)
    started_on = Column(Date, nullable=True)
    ended_on = Column(Date, nullable=True)
    url = Column(String(500), nullable=True)
    # Declared, never computed: "52 planned" beside a measured "46 done" (§3.1).
    declared_target = Column(Text, nullable=True)
    # The RippleTrace container this work is the intent behind. A soft reference (no FK): the
    # container is RippleTrace's table, and this domain owns the link, not the other way round.
    container_id = Column(String, nullable=True, index=True)
    provenance = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkLink(Base):
    __tablename__ = "work_links"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    from_work_id = Column(String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)
    to_work_id = Column(String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)
    relation = Column(String(24), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkObjective(Base):
    """A work serves an objective of the plan (§3.3): the "what was built for it" beside the
    hours `objective_rollup` already counts."""

    __tablename__ = "work_objectives"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    work_id = Column(String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)
    objective_id = Column(String, ForeignKey("plan_objectives.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkRevision(Base):
    """History, not overwrite (§3.4): what the owner thought a work was, before they changed it."""

    __tablename__ = "work_revisions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    work_id = Column(String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)
    field = Column(String(32), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkProposalDismissal(Base):
    """A proposal the owner said no to is not asked again (the container rule, §4.2)."""

    __tablename__ = "work_proposal_dismissals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    proposal_key = Column(String(400), nullable=False, index=True)
    dismissed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
