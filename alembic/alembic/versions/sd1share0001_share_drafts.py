"""Share drafts: what a published piece's drafts are, and which pieces have had them

Owner, 2026-10-25: after a piece is published, A.I.N.D.Y. writes its share drafts (a LinkedIn post, a
short post, a meta description and the previous piece's updated What's Next? footer) into the
Drafts section, from the piece itself. Two columns say what a draft is and which piece it came
from. One says whether a piece has had them.

**New pieces only** (owner): every piece already stored is marked `skipped`, so the workflow starts
with whatever is published after this migration runs. An older piece gets drafts when the owner asks.

Revision ID: sd1share0001
Revises: wk3shared0001
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "sd1share0001"
down_revision: Union[str, None] = "wk3shared0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "work_drafts" in tables:
        have = _columns(inspector, "work_drafts")
        if "kind" not in have:
            op.add_column("work_drafts", sa.Column("kind", sa.String(32), nullable=True))
        if "drop_point_id" not in have:
            op.add_column("work_drafts", sa.Column("drop_point_id", sa.String(), nullable=True))
        op.execute("CREATE INDEX IF NOT EXISTS ix_work_drafts_drop_point_id ON work_drafts (drop_point_id)")
    if "drop_points" in tables:
        if "share_drafts" not in _columns(inspector, "drop_points"):
            op.add_column("drop_points", sa.Column("share_drafts", sa.String(16), nullable=True))
        op.execute("UPDATE drop_points SET share_drafts = 'skipped' WHERE share_drafts IS NULL")


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "drop_points" in tables and "share_drafts" in _columns(inspector, "drop_points"):
        op.drop_column("drop_points", "share_drafts")
    if "work_drafts" in tables:
        op.execute("DROP INDEX IF EXISTS ix_work_drafts_drop_point_id")
        have = _columns(inspector, "work_drafts")
        for column in ("drop_point_id", "kind"):
            if column in have:
                op.drop_column("work_drafts", column)
