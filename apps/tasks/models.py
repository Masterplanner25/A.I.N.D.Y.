from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from AINDY.db.database import Base


class Task(Base):
    """
    Unified Task Model
    Combines performance metrics (from main.py)
    with scheduling, recurrence, and status fields (from models.py).
    Powers A.I.N.D.Y.’s Execution Engine + Reminder System.
    """
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    # --- Core Task Identity ---
    name = Column(String, nullable=False, index=True)
    category = Column(String, default="general")
    priority = Column(String, default="medium")
    status = Column(String, default="pending")  # pending, in_progress, paused, completed
    masterplan_id = Column(Integer, ForeignKey("master_plans.id"), nullable=True, index=True)
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    depends_on = Column(JSON, nullable=False, default=list)
    dependency_type = Column(String, default="hard")
    automation_type = Column(String, nullable=True)
    automation_config = Column(JSON, nullable=True)

    # --- Timing and Scheduling ---
    due_date = Column(DateTime, nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    # ESTIMATED effort in HOURS. Set from the `estimated_hours` create input;
    # consumed by the MasterPlan ETA (apps/masterplan/services/eta_service.py) for
    # continuous-time / effort-weighted projection. Do NOT confuse with
    # `time_spent` below (actual elapsed *seconds*).
    duration = Column(Float, default=0.0)
    scheduled_time = Column(DateTime, nullable=True)
    reminder_time = Column(DateTime, nullable=True)
    recurrence = Column(String, nullable=True)  # daily, weekly, monthly

    # --- Performance & AI Metrics ---
    # ACTUAL elapsed time in SECONDS (accrued via (now - start_time).total_seconds()
    # on start/complete). NOT hours — every consumer treats this as seconds (the
    # client shows time_spent/60 as minutes; completion memory labels it "s").
    # Distinct from `duration` (estimated hours) and from the analytics
    # TaskInput.time_spent API payload (which is caller-supplied hours, a separate
    # path that never reads this column).
    time_spent = Column(Float, default=0.0)  # actual elapsed SECONDS (see note above)
    # ── Strategy layer (STRATEGY_LAYER_SPEC §5) ───────────────────────────────────────
    #
    # Nullable and unread as of 2026-09-07. A task belongs to the strategy it was created to
    # execute, and inherits that strategy's phase; both are carried explicitly rather than
    # derived, because a task can outlive the strategy that spawned it — an abandoned strategy
    # returns its INCOMPLETE tasks to the plan unattached and leaves completed ones untouched
    # (§6 Q4). Cascading to cancelled would destroy the record of work actually done, and would
    # retroactively reduce WCU, which accrues from completed tasks.
    strategy_id = Column(String, nullable=True, index=True)
    phase_id = Column(String, nullable=True, index=True)

    task_complexity = Column(Integer, default=1)
    skill_level = Column(Integer, default=1)
    ai_utilization = Column(Integer, default=0)
    task_difficulty = Column(Integer, default=1)

    # --- Ownership ---
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("User", backref="tasks")
    masterplan = relationship("MasterPlan", backref="tasks")
    parent_task = relationship("Task", remote_side=[id], backref="child_tasks")


def register_models() -> None:
    return None
