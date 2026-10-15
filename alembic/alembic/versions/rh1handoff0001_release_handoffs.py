"""add release_handoffs — a release A.I.N.D.Y. follows to the end after the owner starts it

`RELEASE_HANDOFF_SPEC.md` §4, phase 1. One row per handoff: the repository and tag, the `publish.yml` run
found for it, the stage the watcher has moved it to, and what it recorded. One new table.

Revision ID: rh1handoff0001
Revises: rc2claims0001
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "rh1handoff0001"
down_revision: Union[str, None] = "rc2claims0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "release_handoffs" in set(inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "release_handoffs",
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("repo", sa.String(200), nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("run_url", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(16), nullable=False, index=True),
        sa.Column("stage_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.JSON(), nullable=True),
        sa.Column("notified", sa.JSON(), nullable=True),
        sa.Column("task_id", sa.String(32), nullable=True),
        sa.Column("task_name", sa.String(200), nullable=True),
        sa.Column("adoption_task_id", sa.String(32), nullable=True),
        sa.Column("memory_node_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if "release_handoffs" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("release_handoffs")
