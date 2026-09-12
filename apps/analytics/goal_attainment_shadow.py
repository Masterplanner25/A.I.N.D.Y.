"""Goal-attainment shadow ledger — attainment next to the live plan-progress score.

`MASTERPLAN_GOAL_ATTAINMENT_SPEC` §6 Phase 2, built 2026-09-11 once attribution existed.

Each canonical score computation, when `AINDY_MASTERPLAN_GOAL_ATTAINMENT_SHADOW` is on,
also records what `masterplan_progress` *would* have been with attainment blended in
(§5 formula) next to what it actually was. **Drives nothing.** The live score is computed
exactly as before; this row is the observability that lets a soak show whether attainment
diverges from — or improves on — task-ticking before anything is allowed to move.

The attainment here is *attribution-based*, which is the thing §4b said was missing: hours
completed against each objective through `task → strategy → objective`, hours-weighted to a
plan figure. An objective with no planned work is unmeasured, not zero, and a plan whose
objectives are all unmeasured records `attainment_pct = NULL` and a shadow score equal to
the live one — the fallback the spec makes mandatory.

Owner, 2026-09-11: *"Yes, as a shadow first."* System proposes, human confirms.
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class GoalAttainmentShadowRecord(Base):
    __tablename__ = "goal_attainment_shadow_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    masterplan_id = Column(Integer, nullable=True, index=True)

    # What the live formula produced at this event (unchanged by anything here).
    live_score = Column(Float, nullable=True)
    # What the §5 blend would have produced. Equal to live_score when unmeasured.
    shadow_score = Column(Float, nullable=True)

    # The blend's inputs, so a row is a complete example.
    attainment_pct = Column(Float, nullable=True)       # NULL = no objective has planned work
    completion_pct = Column(Float, nullable=True)
    schedule_score = Column(Float, nullable=True)
    hours_completed = Column(Float, nullable=True)
    hours_total = Column(Float, nullable=True)
    objectives_measured = Column(Integer, nullable=True)
    # [{id, name, hours_total, hours_completed, attainment_pct}] — per objective, as read.
    objectives = Column(JSON, nullable=True)

    trigger_event = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return (
            f"<GoalAttainmentShadowRecord(live={self.live_score}, shadow={self.shadow_score}, "
            f"attainment={self.attainment_pct})>"
        )
