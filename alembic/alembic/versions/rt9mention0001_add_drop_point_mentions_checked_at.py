"""add drop_points.mentions_checked_at (rippletrace echo detection)

Records when the web was last searched for echoes of a drop point. Kept separate from
the narrative/velocity/spread columns because "searched and found nothing" and "never
searched" are different states — only the second justifies spending another search —
and the score columns cannot express that difference.

Additive + guarded (inspector has_column) so it is idempotent on existing and fresh
databases alike.

Revision ID: rt9mention0001
Revises: c7d8e9f0a1b2
Create Date: 2026-08-01 13:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "rt9mention0001"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "drop_points"
_COLUMN = "mentions_checked_at"


def _has_column(bind, table: str, column: str) -> bool:
    insp = inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in inspect(bind).get_table_names():
        return
    if not _has_column(bind, _TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
