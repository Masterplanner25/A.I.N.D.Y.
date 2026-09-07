"""add ripple_containers (a container is confirmed, never inferred)

`drop_points.tagged_entities` has existed since RippleTrace was built and three engines read it
— influence_graph links drops by shared entity, causal_engine feeds them into causal reasons,
and strategy_engine builds "{entity} Influence Spike" strategies from them. It held **one row
out of 215**, so that last path had never once fired. The missing input was not a table; it was
a classification nobody had made (TITLE_AS_CONTAINER_SPEC §3).

This table records the classification. It stores **decisions, not detections**: candidates are
derived from the corpus on demand, and only a container someone confirmed or dismissed gets a
row. Dismissals are kept for the same reason confirmations are — without them the system
re-proposes a rejected candidate on every visit, which turns an answered question into a nag.

Revision ID: rc1container001
Revises: sd1draft0001
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision: str = "rc1container001"
down_revision: Union[str, None] = "sd1draft0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ripple_containers"


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: the app-profile suite runs migrations on
    # SQLite, where the PostgreSQL-only form is unavailable. Same idempotency guarantee,
    # portable (MIGRATION_POLICY.md).
    bind = op.get_bind()
    if _TABLE in set(inspect(bind).get_table_names()):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        # As the author wrote it. The name is an identity, and casing is part of it.
        sa.Column("name", sa.String(300), nullable=False),
        # What matching runs against. Stored rather than derived at read time so a change to
        # normalisation cannot silently re-scope an existing container.
        sa.Column("normalized", sa.String(300), nullable=False, index=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="confirmed", index=True
        ),
        sa.Column("drop_count_at_decision", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE in set(inspect(bind).get_table_names()):
        op.drop_table(_TABLE)
