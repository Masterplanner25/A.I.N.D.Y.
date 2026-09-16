"""add master_plans.pace_dismissed_at / pace_dismissed_days — the pace proposal can be declined

`BUILD_PLAN` "Risk posture & ETA drift — sensed, not actuated". The actuation is a proposal
(`services/pace.py`): when the projected completion drifts from `target_date` by more than the
posture's tolerance, the system proposes and the human confirms (retarget) or declines. A
declined proposal records the drift it was measured against, the same way `plan_phases.
advance_dismissed_task_count` records the work a phase-advance dismissal was measured against,
and returns only when the drift moves by more than the tolerance — a different question.

Revision ID: pc1pace0001
Revises: lc1contact001
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "pc1pace0001"
down_revision: Union[str, None] = "lc1contact001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "master_plans"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    # is PostgreSQL-only and the app-profile suite runs this on SQLite (MIGRATION_POLICY.md).
    # Both nullable, no default on either side — the parity guard (Step 6) agrees.
    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    if not _has_column(inspector, _TABLE, "pace_dismissed_at"):
        op.add_column(_TABLE, sa.Column("pace_dismissed_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(inspector, _TABLE, "pace_dismissed_days"):
        op.add_column(_TABLE, sa.Column("pace_dismissed_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for column in ("pace_dismissed_days", "pace_dismissed_at"):
        if _has_column(inspector, _TABLE, column):
            op.drop_column(_TABLE, column)
