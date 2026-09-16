"""
LEAD ACTION MODEL
------------------------------------
Part of: A.I.N.D.Y. – Search Execution Layer

The Execution Layer is the act-on-insight half Search was missing: the leadgen
pipeline discovered and scored leads (``LeadGenResult``) but nothing ever acted on
them. A ``LeadAction`` is that acted-upon artifact — one tracked, revertible row per
lead the guarded consumer decides to pursue, carrying the generated outreach draft
and the decision that qualified it.

Safe by construction: the default ``draft`` channel never contacts the lead — it
produces a draft for review and (via the search public surface) for freelance to
convert into a client/order. A real send channel is gated default-off.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class LeadAction(Base):
    """One outreach action taken on a discovered lead (draft-first, revertible)."""

    __tablename__ = "lead_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    lead_id = Column(
        Integer,
        ForeignKey("leadgen_results.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Denormalized lead context (survives lead deletion; drives display + segmenting).
    company = Column(String)
    url = Column(String)
    lead_query = Column(String, nullable=True, index=True)  # leadgen query that produced the lead — the learning segment

    channel = Column(String(16), default="draft", server_default="draft")     # draft | email | handoff
    status = Column(String(16), default="drafted", index=True, server_default="drafted")  # drafted | queued | sent | skipped | reverted

    # The generated outreach artifact (draft channel).
    draft_subject = Column(String)
    draft_body = Column(Text)

    # Why this lead qualified — the gate's decision, for audit.
    decision_score = Column(Float)
    decision_reason = Column(String)

    trigger = Column(String(16), default="manual", server_default="manual")    # manual | agent | scheduler
    note = Column(String)                             # e.g. "send channel disabled"
    # What the email channel actually did. `recipient` is the address a `sent` action went to
    # (copied from the lead at send time, so a later contact edit does not rewrite history);
    # `sent_at` is when. Both NULL for drafted / queued / failed actions.
    recipient = Column(String, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    reverted_at = Column(DateTime(timezone=True), nullable=True)

    # --- Learning close: judge the action against whether the lead actually converted ---
    # After an observation window each non-reverted action is judged on its in-domain
    # conversion signal (SearchResultFeedback: a `convert`/thumbs_up on the lead's url).
    # Outreach isn't reversible, so a segment (lead_query) that consistently fails to convert
    # is AUTO-SUPPRESSED forward — future leads from it are gated out — rather than reverted.
    # NULL outcome = not yet evaluated (pending).
    outcome = Column(String(16), nullable=True, index=True)   # converted | no_response | NULL(pending)
    outcome_signal = Column(Float, nullable=True)             # net conversion feedback weight at eval time
    evaluated_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<LeadAction(company='{self.company}', status='{self.status}')>"
