"""works.shared_name — a name other people or things share

`RESOLUTION_CHECK_SPEC.md` §7.4. Owner, 2026-10-22: Shawn Knight, Nodus and A.I.N.D.Y. are shared
names, so AI search asked by the name alone should list several meanings; resolving to the owner's
is a favour, and missing from the list is a presence gap, not a confusion. Declared by the owner,
never computed. One column with a default; nothing else changes.

Revision ID: wk3shared0001
Revises: rh1handoff0001
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "wk3shared0001"
down_revision: Union[str, None] = "rh1handoff0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "works" not in inspector.get_table_names():
        return
    if "shared_name" not in {c["name"] for c in inspector.get_columns("works")}:
        op.add_column("works", sa.Column("shared_name", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "works" in inspector.get_table_names() and "shared_name" in {
        c["name"] for c in inspector.get_columns("works")
    }:
        op.drop_column("works", "shared_name")
