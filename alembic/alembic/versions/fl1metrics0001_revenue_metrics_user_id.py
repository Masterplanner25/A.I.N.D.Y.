"""Revenue metrics belong to a user

Each row was computed from one user's orders but stored with no owner. Existing rows stay ownerless, and
nobody reads them: the next metrics update writes a row with its owner.

Revision ID: fl1metrics0001
Revises: rt1medium0001
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "fl1metrics0001"
down_revision: Union[str, None] = "rt1medium0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or "revenue_metrics" not in inspect(bind).get_table_names():
        return
    op.execute("ALTER TABLE revenue_metrics ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_revenue_metrics_user_id ON revenue_metrics (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_revenue_metrics_user_id")
    op.execute("ALTER TABLE revenue_metrics DROP COLUMN IF EXISTS user_id")
