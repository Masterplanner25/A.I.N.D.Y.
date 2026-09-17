"""add plan_strategies.conclude_dismissed_at / conclude_dismissed_task_count — the conclude proposal can be declined

`STRATEGY_LAYER_SPEC` §8 step 3b(v): a strategy whose every attached task is complete is
proposed for a verdict (`services/strategy_conclude.py`); the human concludes it with the
existing verdict routes or declines. A declined proposal records the task count it was measured
against — the same pair `plan_phases.advance_dismissed_*` carries — and returns only when that
count changes, which is a different question.

Revision ID: sc1concl0001
Revises: pc1pace0001
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "sc1concl0001"
down_revision: Union[str, None] = "pc1pace0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "plan_strategies"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: the app-profile suite runs this on
    # SQLite (MIGRATION_POLICY.md). Both nullable, no default on either side — the parity
    # guard (Step 6) agrees.
    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    if not _has_column(inspector, _TABLE, "conclude_dismissed_at"):
        op.add_column(_TABLE, sa.Column("conclude_dismissed_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(inspector, _TABLE, "conclude_dismissed_task_count"):
        op.add_column(_TABLE, sa.Column("conclude_dismissed_task_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for column in ("conclude_dismissed_task_count", "conclude_dismissed_at"):
        if _has_column(inspector, _TABLE, column):
            op.drop_column(_TABLE, column)
