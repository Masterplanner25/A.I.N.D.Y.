import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from AINDY.db.database import Base


class Goal(Base):
    __tablename__ = "goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    goal_type = Column(String(32), nullable=False, default="strategic", index=True)
    priority = Column(Float, nullable=False, default=0.5, server_default="0.5")
    status = Column(String(32), nullable=False, default="active", index=True, server_default="active")
    success_metric = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'"))
    # GOALS_LAYER_SPEC §2 (2026-11-09): where the goal came from and how its progress is measured. A goal belongs to
    # the person and outlives plan versions; `masterplan_id` is provenance only.
    source = Column(String(32), nullable=True)            # anchor | success_criterion | stated
    measure = Column(String(32), nullable=True)           # anchor | objectives | declared (§4)
    masterplan_id = Column(Integer, nullable=True, index=True)
    target_value = Column(Float, nullable=True)           # an anchor goal's number
    unit = Column(String(32), nullable=True)
    target_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class GoalObjective(Base):
    """A plan objective that serves a goal (GOALS_LAYER_SPEC §2). A pointer from the person's layer into one plan;
    strategies are never linked to goals (STRATEGY_LAYER_SPEC §6 Q1)."""

    __tablename__ = "goal_objectives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_id = Column(UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True)
    objective_id = Column(String, ForeignKey("plan_objectives.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

