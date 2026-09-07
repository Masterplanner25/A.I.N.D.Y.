"""A container: the project or series a piece of work belongs to.

`TITLE_AS_CONTAINER_SPEC` §4. The owner's reframe:

> *"For me specifically the title is a container so to speak — it contains the project or
> entity that is later to be referenced. So '2025 ChatGPT Case Study Series' is a mechanism as
> well as a name."*

`drop_points.tagged_entities` has existed since RippleTrace was built and three engines read it
— `influence_graph` links drops by shared entity, `causal_engine` feeds them into causal
reasons, and `strategy_engine` builds `{entity} Influence Spike` strategies from them. It held
**one row out of 215**, so that last code path had never once fired. The missing input was not a
table; it was a classification nobody had made.

★ **A container is confirmed, never inferred.** Owner's call, 2026-09-07. The corpus can measure
which words recur across a catalogue, but "these four words recur" is a measurement and "this is
a work I made" is an identity — and three engines reason from the second. An inferred identity
that is wrong is worse than none, because everything downstream would treat it as a fact about
the author's body of work.

So this table records **decisions**, not detections. A candidate that has been neither confirmed
nor dismissed has no row here at all.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base

# What a person did about a proposed container. There is no "pending": a candidate the system
# has noticed but nobody has answered is derived on demand from the corpus, so it cannot drift
# out of step with the drops it was derived from.
CONTAINER_CONFIRMED = "confirmed"
CONTAINER_DISMISSED = "dismissed"
VALID_CONTAINER_STATUSES = {CONTAINER_CONFIRMED, CONTAINER_DISMISSED}


class ContainerDB(Base):
    """One confirmed-or-dismissed container, per user.

    Dismissals are stored for the same reason confirmations are: without them the system would
    re-propose a rejected candidate on every visit, which turns a question that was answered
    into a nag.
    """

    __tablename__ = "ripple_containers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # As it reads in the author's own titles — "2025 ChatGPT Case Study Series", not
    # "2025 chatgpt case study series". The name is an identity; casing is part of it.
    name = Column(String(300), nullable=False)
    # The lowercased token sequence, which is what matching runs against. Stored rather than
    # derived at read time so a change to normalisation cannot silently re-scope an existing
    # container.
    normalized = Column(String(300), nullable=False, index=True)

    status = Column(String(16), nullable=False, default=CONTAINER_CONFIRMED, index=True)

    # What the corpus said when the person answered. Kept as a record of the evidence they were
    # shown, not as a live count — the live count is a query.
    drop_count_at_decision = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ContainerDB(name={self.name!r}, status={self.status})>"
