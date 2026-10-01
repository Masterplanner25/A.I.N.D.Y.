"""add work_drafts — what the agent writes for the owner, as documents

Owner, 2026-09-30: "where does the output go once it does generate/do something?" A run's writing
went to a step result, a memory node and a task. `content.draft` now saves a draft here, listed in
Collaborator's Work mode with the run that wrote it and its sources. One new table.

Revision ID: wd1draft0001
Revises: dp1content0001
Create Date: 2026-09-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "wd1draft0001"
down_revision: Union[str, None] = "dp1content0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Inspector-guarded (SQLite runs this too); only the timestamps carry server defaults.
    if "work_drafts" in set(inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "work_drafts",
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("run_id", sa.String(), nullable=True, index=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    if "work_drafts" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("work_drafts")
