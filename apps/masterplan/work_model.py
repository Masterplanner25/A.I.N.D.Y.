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

from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base

# ── Vocabularies (closed, validated in the service) ─────────────────────────────────────────

# `person` and `brand` added 2026-09-30 (RESOLUTION_CHECK_SPEC §7 decision 1): the owner and their brand are
# entities AI search must resolve, so they are Works with summaries and links like the rest.
WORK_KINDS = ("project", "product", "series", "practice", "publication", "person", "brand", "other")
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
    # Added 2026-09-30 for the person and brand kinds: "Shawn Knight created Masterplan Infinite Weave".
    "created": "created or founded",
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
    # How the owner judges whether this work is succeeding, in their words. Declared, never computed.
    # Added 2026-09-30: a plan for Nodus drafted from the owner's own AI Search writing still closed on
    # the industry's metrics (indexing rate, citation counts), because nothing held the owner's.
    # Theirs, for AI Search Optimization: resolution, not rankings.
    success_criteria = Column(Text, nullable=True)
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


class WorkDraft(Base):
    """Something the agent wrote for the owner: a plan, an outline, an article draft.

    Owner, 2026-09-30: *"where does the output go once it does generate/do something?"* Until this,
    a run's writing went to a step result, a memory node and a task: places the agent can reach and
    the owner cannot read. A draft is a document, listed in Collaborator's Work mode with the run
    that wrote it and the sources it drew on.
    """

    __tablename__ = "work_drafts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    # The agent run that wrote it, when one did (a soft reference: runs are the runtime's).
    run_id = Column(String, nullable=True, index=True)
    # The Work it is for, when the brief named one.
    work_id = Column(String, ForeignKey("works.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(300), nullable=False)
    brief = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    # [{"title", "url", "platform", "kind"}]: what it was written from, in citation order ([S1] …).
    sources = Column(JSON, nullable=True)
    model = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkPresence(Base):
    """Where a Work is on the web, and what it says about itself there (RESOLUTION_CHECK_SPEC §2.2).

    Owner, 2026-09-30: *"we don't need it to pull all the content from across the web, but we can use
    the content/sites as a control … these things are also connections."* Declared by the owner, never
    crawled: the header on LinkedIn, the bio on Facebook, the publication line on Medium. Each is a
    canonical statement to check answers against, and a connection an engine should make.
    """

    __tablename__ = "work_presence"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    work_id = Column(String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(64), nullable=False)
    url = Column(String(500), nullable=True)
    # The header or bio, in the owner's words, as it reads on that platform.
    self_description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ResolutionRun(Base):
    """One resolution check (RESOLUTION_CHECK_SPEC): the questions asked, to which engines, and how far
    it has got. Answered a few at a time by a scheduled tick, so a check never holds the api."""

    __tablename__ = "resolution_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    scope = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, index=True)
    questions = Column(JSON, nullable=False)
    engines = Column(JSON, nullable=False)
    calls = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class ResolutionAnswer(Base):
    """One engine's answer to one question, raw, with the judge's facts and the scores code computed."""

    __tablename__ = "resolution_answers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    run_id = Column(String, ForeignKey("resolution_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    question_key = Column(String(200), nullable=False)
    engine = Column(String(64), nullable=False)
    answer = Column(Text, nullable=True)
    citations = Column(JSON, nullable=True)
    judgement = Column(JSON, nullable=True)
    scores = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
