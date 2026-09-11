"""add plan_phases.advance_dismissed_at / advance_dismissed_task_count — the human can say "not done"

`STRATEGY_LAYER_SPEC` §6 Q8 built phase advance as a proposal the human confirms. The first
live proposal (2026-09-10, *Foundation Building*, 2 of 2 tasks complete, 360 days inside its
window) drew the obvious response — *"what if the phase isn't complete?"* — and there was no
way to say so. A proposal that can only be accepted is not a proposal.

Dismissal records the evidence it was built on (`advance_dismissed_task_count`), not just when.
The proposal stays quiet while the phase's attached work is unchanged and comes back the moment
a task is added or removed — the only thing that could change the answer.

Revision ID: pd1dismiss001
Revises: pv1verify0001
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "pd1dismiss001"
down_revision: Union[str, None] = "pv1verify0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "plan_phases"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    # is PostgreSQL-only and the app-profile suite runs this on SQLite (MIGRATION_POLICY.md).
    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    if not _has_column(inspector, _TABLE, "advance_dismissed_at"):
        op.add_column(
            _TABLE, sa.Column("advance_dismissed_at", sa.DateTime(timezone=True), nullable=True)
        )
    if not _has_column(inspector, _TABLE, "advance_dismissed_task_count"):
        op.add_column(
            _TABLE, sa.Column("advance_dismissed_task_count", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for column in ("advance_dismissed_task_count", "advance_dismissed_at"):
        if _has_column(inspector, _TABLE, column):
            op.drop_column(_TABLE, column)
