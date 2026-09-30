"""drop_points content columns — the published writing, and the hash its memory was written from

`WORK_MODEL_SPEC.md` §5, phase B. The text of each published piece, bounded (the service caps it),
with where it came from and a hash, so memory chunks are rewritten only when the text changes.
Additive and nullable; no server defaults, so the schema-default parity guard agrees.

Revision ID: dp1content0001
Revises: sg1leadseg0001
Create Date: 2026-09-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "dp1content0001"
down_revision: Union[str, None] = "sg1leadseg0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("content_text", sa.Text()),
    ("content_source", sa.String(16)),
    ("content_fetched_at", sa.DateTime(timezone=True)),
    ("content_hash", sa.String(64)),
    ("content_memory_hash", sa.String(64)),
)


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "drop_points" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("drop_points")}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column("drop_points", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "drop_points" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("drop_points")}
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("drop_points", name)
