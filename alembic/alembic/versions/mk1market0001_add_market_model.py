"""add market_segments, segment_works, market_entities, market_evidence, market_revisions, market_proposals

`MARKET_MODEL_SPEC.md` §3, phase A. Who the owner's work is for (a segment: a bet with a status),
which works serve it, what surrounds the buyer, the evidence behind each bet, a segment's history,
and proposals with their answers. Six new tables; nothing existing is altered.

Revision ID: mk1market0001
Revises: wk1work0001
Create Date: 2026-09-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "mk1market0001"
down_revision: Union[str, None] = "wk1work0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user_id_column():
    return sa.Column(
        "user_id",
        postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
        sa.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )


def _stamp(name: str = "created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _segment_fk(nullable: bool, ondelete: str):
    return sa.Column(
        "segment_id", sa.String(), sa.ForeignKey("market_segments.id", ondelete=ondelete),
        nullable=nullable, index=True,
    )


def upgrade() -> None:
    # Inspector-guarded, as wk1work0001: the app-profile suite runs migrations on SQLite. Only the
    # timestamps carry server defaults, matching the models, so the schema-default parity guard agrees.
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())

    if "market_segments" not in existing:
        op.create_table(
            "market_segments",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id_column(),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("buyer", sa.Text(), nullable=False),
            sa.Column("problem", sa.Text(), nullable=True),
            sa.Column("trigger", sa.Text(), nullable=True),
            sa.Column("category_terms", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("provenance", sa.String(16), nullable=False),
            _stamp(),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "segment_works" not in existing:
        op.create_table(
            "segment_works",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _segment_fk(False, "CASCADE"),
            sa.Column("work_id", sa.String(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True),
            _stamp(),
        )

    if "market_entities" not in existing:
        op.create_table(
            "market_entities",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id_column(),
            _segment_fk(True, "SET NULL"),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("url", sa.String(1000), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("provenance", sa.String(16), nullable=False),
            _stamp(),
        )

    if "market_evidence" not in existing:
        op.create_table(
            "market_evidence",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id_column(),
            _segment_fk(True, "CASCADE"),
            sa.Column("entity_id", sa.String(), sa.ForeignKey("market_entities.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("claim", sa.Text(), nullable=False),
            sa.Column("source_url", sa.String(1000), nullable=True),
            sa.Column("source_kind", sa.String(16), nullable=False),
            sa.Column("stance", sa.String(16), nullable=False),
            _stamp("captured_at"),
        )

    if "market_revisions" not in existing:
        op.create_table(
            "market_revisions",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _segment_fk(False, "CASCADE"),
            sa.Column("field", sa.String(32), nullable=False),
            sa.Column("old_value", sa.Text(), nullable=True),
            sa.Column("new_value", sa.Text(), nullable=True),
            _stamp("changed_at"),
        )

    if "market_proposals" not in existing:
        op.create_table(
            "market_proposals",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id_column(),
            sa.Column("proposal_key", sa.String(400), nullable=False, index=True),
            sa.Column("source", sa.String(24), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False),
            _stamp(),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in ("market_proposals", "market_revisions", "market_evidence", "market_entities",
                  "segment_works", "market_segments"):
        if table in existing:
            op.drop_table(table)
