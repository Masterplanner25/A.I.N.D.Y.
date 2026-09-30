"""The market — who the owner's work is for, what surrounds that buyer, and why each bet is believed.

`MARKET_MODEL_SPEC.md` §3. The companion to `work_model.py`, with one difference that shapes every
table here: **a Work is a fact; a market is a bet.** A segment carries a status (`hypothesis` →
`validated` / `abandoned`) and the evidence behind it, and the planner is always told which.

The same house rule as Works: nothing reaches these tables unless the owner declared it or confirmed
a proposal. The agent may propose (`market.propose`); only the owner confirms.
"""
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base

# ── Vocabularies (closed, validated in the service) ─────────────────────────────────────────

# §3.1: a bet, stated as one.
SEGMENT_STATUSES = ("hypothesis", "testing", "validated", "abandoned")

# §3.2: five kinds, the ones the first three misfiled "leads" needed. A free-text kind is a label
# nothing can reason over (the `work_links.relation` rule).
ENTITY_KINDS = {
    "alternative": "what the buyer would choose instead, including building it themselves or doing nothing",
    "channel": "where the buyer gathers or looks: a forum, job board, publication or event",
    "intermediary": "who sells, integrates or recommends to the buyer",
    "voice": "who shapes how the buyer thinks: analysts, newsletters, practitioners",
    "exemplar": "a named organisation that fits the segment",
}

MARKET_PROVENANCE = ("declared", "confirmed")
EVIDENCE_SOURCES = ("research", "lead_outcome", "owner")
EVIDENCE_STANCES = ("supports", "contradicts")
PROPOSAL_STATUSES = ("open", "confirmed", "dismissed")


class MarketSegment(Base):
    __tablename__ = "market_segments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    # Who decides, and in what kind of organisation.
    buyer = Column(Text, nullable=False)
    # The problem in the BUYER's words, not the product's.
    problem = Column(Text, nullable=True)
    trigger = Column(Text, nullable=True)
    # What the buyer calls the thing they would buy: the search vocabulary of phase B (§5.2).
    category_terms = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False)
    provenance = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SegmentWork(Base):
    """Which of the owner's works serves this segment (§3.1): the join the lead scorer lacks."""

    __tablename__ = "segment_works"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    segment_id = Column(String, ForeignKey("market_segments.id", ondelete="CASCADE"), nullable=False, index=True)
    work_id = Column(String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MarketEntity(Base):
    """What surrounds the buyer (§3.2). `segment_id` is optional: a competitor can span segments."""

    __tablename__ = "market_entities"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    segment_id = Column(String, ForeignKey("market_segments.id", ondelete="SET NULL"), nullable=True, index=True)
    kind = Column(String(16), nullable=False)
    name = Column(String(300), nullable=False)
    url = Column(String(1000), nullable=True)
    note = Column(Text, nullable=True)
    provenance = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MarketEvidence(Base):
    """Why a bet is believed, or doubted (§3.3). Attached to a segment or an entity."""

    __tablename__ = "market_evidence"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    segment_id = Column(String, ForeignKey("market_segments.id", ondelete="CASCADE"), nullable=True, index=True)
    entity_id = Column(String, ForeignKey("market_entities.id", ondelete="CASCADE"), nullable=True, index=True)
    claim = Column(Text, nullable=False)
    source_url = Column(String(1000), nullable=True)
    source_kind = Column(String(16), nullable=False)
    stance = Column(String(16), nullable=False)
    captured_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MarketRevision(Base):
    """History, not overwrite: what a segment said before, above all its status."""

    __tablename__ = "market_revisions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    segment_id = Column(String, ForeignKey("market_segments.id", ondelete="CASCADE"), nullable=False, index=True)
    field = Column(String(32), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MarketProposal(Base):
    """A proposal and its answer (§4).

    Proposals the system derives on demand (a saved lead nobody acted on) are stored only once
    answered, keyed by `proposal_key`, so a declined one is not asked again. Proposals the agent
    makes (`market.propose`) are stored when made, `status="open"`, because nothing else holds them.
    """

    __tablename__ = "market_proposals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    proposal_key = Column(String(400), nullable=False, index=True)
    source = Column(String(24), nullable=False)
    payload = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
