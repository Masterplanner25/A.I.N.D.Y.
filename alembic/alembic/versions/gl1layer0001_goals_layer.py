"""Goals as a user-level layer: source, measure, the anchor's number, and links to objectives

GOALS_LAYER_SPEC phase A (owner's decisions, 2026-11-09). New columns on `goals` say where a goal came from and how its
progress is measured; `goal_objectives` links a goal to the plan objectives that serve it; `goal_states.progress`
becomes nullable, because a declared goal has no progress number (decision 2).

`goals` and `goal_states` have never held a row, so there is nothing to backfill. Additive and guarded, like every app
migration.

Revision ID: gl1layer0001
Revises: rt3answers0001
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "gl1layer0001"
down_revision: Union[str, None] = "rt3answers0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GOAL_COLUMNS = (
    ("source", sa.String(32)),
    ("measure", sa.String(32)),
    ("masterplan_id", sa.Integer()),
    ("target_value", sa.Float()),
    ("unit", sa.String(32)),
    ("target_date", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "goals" in tables:
        existing = {c["name"] for c in inspector.get_columns("goals")}
        for name, type_ in _GOAL_COLUMNS:
            if name not in existing:
                op.add_column("goals", sa.Column(name, type_, nullable=True))
        indexes = {i["name"] for i in inspector.get_indexes("goals")}
        if "ix_goals_masterplan_id" not in indexes:
            op.create_index("ix_goals_masterplan_id", "goals", ["masterplan_id"])
    if "goal_states" in tables:
        progress = next((c for c in inspector.get_columns("goal_states") if c["name"] == "progress"), None)
        if progress is not None and not progress.get("nullable", True):
            op.alter_column("goal_states", "progress", existing_type=sa.Float(), nullable=True)
    if "goal_objectives" not in tables:
        op.create_table(
            "goal_objectives",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("goal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goals.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("objective_id", sa.String(), sa.ForeignKey("plan_objectives.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_goal_objectives_goal_id", "goal_objectives", ["goal_id"])
        op.create_index("ix_goal_objectives_objective_id", "goal_objectives", ["objective_id"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "goal_objectives" in tables:
        op.drop_table("goal_objectives")
    if "goals" in tables:
        existing = {c["name"] for c in inspector.get_columns("goals")}
        indexes = {i["name"] for i in inspector.get_indexes("goals")}
        if "ix_goals_masterplan_id" in indexes:
            op.drop_index("ix_goals_masterplan_id", table_name="goals")
        for name, _ in _GOAL_COLUMNS:
            if name in existing:
                op.drop_column("goals", name)
