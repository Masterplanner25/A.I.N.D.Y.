"""
Intent value declaration — the Worth axis's *declared prior* (three-axis score model,
Phase A).

The canonical Infinity score measures throughput, not worth. The Worth axis (see
`docs/infinity/INFINITY_SCORE_MODEL.md`) needs a value estimate for work, and realized
money alone fails the proving case — Nodus / aindy-runtime earned $0 yet are high-worth.
So worth starts from a *declared prior*: the user tags a task / masterplan / project with
the value it holds (intrinsic, strategic, or monetary-potential), independent of revenue.

App-owned, observability only in Phase A — it feeds the three-axis snapshot, never the
canonical `master_score`. Realized outcomes (freelance revenue) are the eventual label that
corrects these priors; a learned model is the eventual correction (Phase C+).
"""

import uuid

from sqlalchemy import Column, String, Float, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base

# What flavor of worth the declaration expresses (interpretable, not enforced).
VALID_WORTH_KINDS = {"monetary_potential", "intrinsic", "strategic"}
VALID_TARGET_TYPES = {"task", "masterplan", "project", "other"}


class IntentValueDeclaration(Base):
    __tablename__ = "intent_value_declarations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    target_type = Column(String(16), nullable=False, index=True)   # task | masterplan | project | other
    target_id = Column(String, nullable=True, index=True)          # id of the tagged thing (freeform allowed)
    label = Column(String, nullable=True)                          # human name, e.g. "Nodus language"

    declared_value = Column(Float, nullable=False, default=0.0)    # the worth the user assigns (relative or $-potential)
    kind = Column(String(16), nullable=False, default="strategic") # monetary_potential | intrinsic | strategic
    note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<IntentValueDeclaration(target={self.target_type}:{self.target_id}, value={self.declared_value}, kind={self.kind})>"
