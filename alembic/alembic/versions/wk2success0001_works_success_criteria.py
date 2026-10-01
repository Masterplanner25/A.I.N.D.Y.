"""works.success_criteria — how the owner judges a work, in their words

`WORK_MODEL_SPEC.md` §3.1. Declared, never computed. A plan drafted from the owner's own AI Search
writing (2026-09-30) still closed on industry metrics because nothing held the owner's own measure.
One nullable column; nothing else changes.

Revision ID: wk2success0001
Revises: wd1draft0001
Create Date: 2026-09-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "wk2success0001"
down_revision: Union[str, None] = "wd1draft0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "works" not in inspector.get_table_names():
        return
    if "success_criteria" not in {c["name"] for c in inspector.get_columns("works")}:
        op.add_column("works", sa.Column("success_criteria", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "works" in inspector.get_table_names() and "success_criteria" in {
        c["name"] for c in inspector.get_columns("works")
    }:
        op.drop_column("works", "success_criteria")
