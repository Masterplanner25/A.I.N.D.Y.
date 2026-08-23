"""
Three-axis shadow ledger — the Worth/Volume/Trajectory time-series (three-axis model,
Phase B).

Each canonical score computation, when `AINDY_INFINITY_THREE_AXIS_SHADOW` is on, also
records the three axes next to `master_score` here. Drives nothing — it is the
observability that lets a soak show whether the three-axis model diverges from (or improves
on) the behavioral score before any decision to let it drive scoring (Phase C+). Each row is
a complete example, so the ledger is self-sufficient. See
`docs/infinity/INFINITY_SCORE_MODEL.md`.
"""

import uuid

from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class ThreeAxisShadowRecord(Base):
    __tablename__ = "three_axis_shadow_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    master_score = Column(Float, nullable=True)        # the canonical score at this event (unchanged)
    volume_score = Column(Float, nullable=True)
    worth_score = Column(Float, nullable=True)
    trajectory_score = Column(Float, nullable=True)    # nullable — no estimated completed tasks yet

    # raw components (interpretable next to the normalized axis scores)
    effort_hours = Column(Float, nullable=True)
    completed_count = Column(Integer, nullable=True)
    declared_total = Column(Float, nullable=True)
    realized_revenue = Column(Float, nullable=True)
    mean_pace_ratio = Column(Float, nullable=True)

    trigger_event = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return f"<ThreeAxisShadowRecord(master={self.master_score}, V={self.volume_score}, W={self.worth_score}, T={self.trajectory_score})>"
