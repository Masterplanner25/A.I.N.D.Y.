import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from AINDY.db.database import Base


class GoalState(Base):
    __tablename__ = "goal_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_id = Column(UUID(as_uuid=True), ForeignKey("goals.id"), nullable=False, unique=True, index=True)
    # Null for a declared goal, which has no progress number (GOALS_LAYER_SPEC §4, decision 2).
    progress = Column(Float, nullable=True, default=0.0, server_default="0")
    last_update = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    recent_actions = Column(JSONB, nullable=False, default=list, server_default=text("'[]'"))
    success_signal = Column(Float, nullable=False, default=0.0, server_default="0")
