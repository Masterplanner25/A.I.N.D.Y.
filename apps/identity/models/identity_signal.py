"""
IDENTITY SIGNAL
------------------------------------
Part of: A.I.N.D.Y. — Identity inference (rules -> evidence model)

The raw evidence behind an inferred identity. The rules-only `observe()` flipped a
UserIdentity dimension on a single observation (one high-quality analysis set
speed_vs_quality="quality" forever; one file made a language "preferred"). This table
accumulates each observation as a weighted, provenance-tagged vote so inference becomes
probabilistic — a dimension is committed only when the weighted evidence is confident
and stable, and counter-evidence can move it. One row per observed signal; the derived
verdict still lands on the runtime `UserIdentity` fields (unchanged downstream).
"""

import uuid

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class IdentitySignal(Base):
    __tablename__ = "identity_signals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    dimension = Column(String(32), nullable=False, index=True)   # risk_tolerance | speed_vs_quality | language | ...
    value = Column(String(64), nullable=False, index=True)       # the categorical candidate this observation votes for
    weight = Column(Float, nullable=False, default=1.0, server_default="1")          # evidence strength of this observation
    event_type = Column(String(64), nullable=True)              # provenance (arm_analysis_complete, masterplan_locked, ...)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return f"<IdentitySignal(dimension='{self.dimension}', value='{self.value}', weight={self.weight})>"
