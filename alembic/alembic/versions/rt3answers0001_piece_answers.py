"""What each published piece answers, stored per version of its text

ARTICLE_ANSWERS_SPEC phase B2 (owner's decisions, 2026-11-08): a table of answers per piece and
content hash, and a status on each drop point.

**New pieces only** (decision 3): every piece already stored is marked `skipped`, so answers start
with whatever is published after this migration runs. An older piece gets answers when the owner asks.

Additive and guarded, like every app migration.

Revision ID: rt3answers0001
Revises: rt2links0001
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "rt3answers0001"
down_revision: Union[str, None] = "rt2links0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "piece_answers" not in tables:
        op.create_table(
            "piece_answers",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("drop_point_id", sa.String(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("answers", sa.JSON(), nullable=False),
            sa.Column("raised", sa.JSON(), nullable=False),
            sa.Column("answer_range", sa.JSON(), nullable=False),
            sa.Column("model", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("drop_point_id", "content_hash", name="uq_piece_answers_drop_point_hash"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_piece_answers_user_id ON piece_answers (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_piece_answers_drop_point_id ON piece_answers (drop_point_id)")
    if "drop_points" in tables:
        if "answers" not in {c["name"] for c in inspector.get_columns("drop_points")}:
            op.add_column("drop_points", sa.Column("answers", sa.String(16), nullable=True))
        op.execute("UPDATE drop_points SET answers = 'skipped' WHERE answers IS NULL")


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "drop_points" in tables and "answers" in {c["name"] for c in inspector.get_columns("drop_points")}:
        op.drop_column("drop_points", "answers")
    if "piece_answers" in tables:
        op.drop_table("piece_answers")
