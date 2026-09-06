"""add ordinal_level to intent_value_declarations (Worth: ordinal for non-monetary kinds)

The Worth axis's declared prior accepted a free float for all three kinds. For
``monetary_potential`` that is correct — dollars are genuinely cardinal, $100k really is
twice $50k. For ``intrinsic`` and ``strategic`` it was an unanchored number: nothing
distinguished 8 from 7, nothing bounded it, and the per-kind scale constant could not be
calibrated against a range that did not exist.

Those two kinds now take an ORDINAL level, and this column stores the level the user
actually chose. The mapped float still lives in ``declared_value`` so the scoring maths is
unchanged, but the level is persisted rather than reverse-derived: a reverse mapping would
silently reinterpret every historical row if the constants were ever retuned, which is the
same class of trap as the seconds/hours confusion in Task.time_spent.

Nullable, because ``monetary_potential`` rows legitimately have no level.

Revision ID: w1k2ord3lvl4
Revises: gx7transcript01
Create Date: 2026-09-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "w1k2ord3lvl4"
down_revision: Union[str, None] = "gx7transcript01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "intent_value_declarations"
_COLUMN = "ordinal_level"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: ALTER TABLE ... ADD COLUMN IF NOT
    # EXISTS is PostgreSQL-only, and the app-profile test suite runs this on SQLite.
    # Same idempotency guarantee, portable (MIGRATION_POLICY.md).
    bind = op.get_bind()
    inspector = inspect(bind)
    if _has_column(inspector, _TABLE, _COLUMN):
        return
    if _TABLE not in inspector.get_table_names():
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(16), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _has_column(inspector, _TABLE, _COLUMN):
        return
    op.drop_column(_TABLE, _COLUMN)
