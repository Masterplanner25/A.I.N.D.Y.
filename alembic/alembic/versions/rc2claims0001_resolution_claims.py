"""add resolution_claims — the owner's answers to claims the engines made

`RESOLUTION_CHECK_SPEC.md` §3, phase B. A claim the confirmed facts could not settle goes to the owner;
their answer (true, false, skip) is kept here and feeds the next check's ground truth. One new table.

Revision ID: rc2claims0001
Revises: rc1resolve0001
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "rc2claims0001"
down_revision: Union[str, None] = "rc1resolve0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "resolution_claims" in set(inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "resolution_claims",
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("claim_key", sa.String(400), nullable=False, index=True),
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    if "resolution_claims" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("resolution_claims")
