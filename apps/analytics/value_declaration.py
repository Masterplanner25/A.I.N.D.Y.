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
# `domain` is a MasterPlan core domain — the thing Genesis actually talks about. Worth is
# stated in Genesis against a domain ("the ethics framework is critical"), and before this
# existed the only home for it was `other`, which loses the fact that the target is a named
# part of a plan and makes the row unjoinable to anything.
VALID_TARGET_TYPES = {"task", "masterplan", "project", "domain", "other"}

# ★ Two kinds are ORDINAL, one is CARDINAL — and that asymmetry is the point.
#
# `monetary_potential` is dollars: genuinely cardinal, and $100k really is twice $50k, so it
# keeps a free float. `intrinsic` and `strategic` were also free floats, which was false
# precision — nothing distinguished 8 from 7, nothing bounded the value, and an unbounded
# rating can saturate the axis just as the un-scaled monetary figure used to
# (SOAK_AUDIT_2026-08-15 §2b).
#
# The mapping is roughly geometric because worth judgements are order-of-magnitude ones: the
# gap between "low" and "high" is not one step of something, it is a different class of thing.
#
# ★ These numbers are a CONTRACT, not a tuning knob. `ordinal_level` persists the level the
# user chose, so retuning these does not silently reinterpret history — but a change still
# alters every existing row's contribution to the score. `test_worth_ordinal_levels` pins them
# so a change is deliberate and visible in review.
WORTH_ORDINAL_LEVELS: dict[str, float] = {
    "low": 1.0,
    "moderate": 3.0,
    "high": 8.0,
    "critical": 20.0,
}
ORDINAL_WORTH_KINDS = {"intrinsic", "strategic"}
CARDINAL_WORTH_KINDS = {"monetary_potential"}


class IntentValueDeclaration(Base):
    __tablename__ = "intent_value_declarations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    target_type = Column(String(16), nullable=False, index=True)   # task | masterplan | project | domain | other
    target_id = Column(String, nullable=True, index=True)          # id of the tagged thing (freeform allowed)
    label = Column(String, nullable=True)                          # human name, e.g. "Nodus language"

    # For a cardinal kind this is the declared figure (dollars). For an ordinal kind it is
    # the MAPPED value of `ordinal_level` — scoring reads this field either way, so the
    # per-kind maths in three_axis_service is unchanged.
    declared_value = Column(Float, nullable=False, default=0.0)
    kind = Column(String(16), nullable=False, default="strategic") # monetary_potential | intrinsic | strategic
    # What the user actually chose, for ordinal kinds; NULL for monetary_potential. Persisted
    # rather than reverse-derived from declared_value: a reverse mapping would silently
    # reinterpret every historical row if WORTH_ORDINAL_LEVELS were ever retuned.
    ordinal_level = Column(String(16), nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        shown = self.ordinal_level or self.declared_value
        return f"<IntentValueDeclaration(target={self.target_type}:{self.target_id}, value={shown}, kind={self.kind})>"
