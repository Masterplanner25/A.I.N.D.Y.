"""Directing events: prompts the person sent an agent (times and ids, never text)

DIRECTING_TIME_SPEC phase A (owner's decisions, 2026-11-16). One row per typed prompt; `(user_id, source,
source_event_id)` is unique so the live hook and the transcript backfill can overlap. New table, additive and guarded,
like every app migration.

Revision ID: dt1directing0001
Revises: gl1layer0001
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "dt1directing0001"
down_revision: Union[str, None] = "gl1layer0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "directing_events" in set(inspector.get_table_names()):
        return
    op.create_table(
        "directing_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("project", sa.String(255), nullable=False),
        sa.Column("agent_session_id", sa.String(64), nullable=False),
        sa.Column("source_event_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "source", "source_event_id", name="uq_directing_events_source_event"),
    )
    op.create_index("ix_directing_events_user_id", "directing_events", ["user_id"])
    op.create_index("ix_directing_events_user_occurred", "directing_events", ["user_id", "occurred_at"])


def downgrade() -> None:
    if "directing_events" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("directing_events")
