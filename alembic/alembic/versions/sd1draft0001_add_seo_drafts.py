"""add seo_drafts and seo_draft_analyses (the SEO tool's draft loop)

Every analysis the SEO tool produced was a measurement taken once. `search_history` rows
existed, but nothing said two of them were the same piece at different times, so the
before/after question — which is most of why saving is wanted — could not be asked at all
(`SEO_EDITING_AID_SPEC` §4).

Two tables. A draft is the unit the writer names and keeps; an analysis is one reading of it.
Every analysis is retained: the owner's call is that pruning is *proposed by the system and
confirmed by a person*, never silent, because a silent cap would discard exactly the early
readings that make a comparison possible, at the moment the history became long enough to be
worth having.

`published_url` on the draft is carried from the start. It is the one field that makes a draft
matchable to the RippleTrace drop point it becomes, and adding it later would mean it is null
for every draft written before someone thought of it.

Revision ID: sd1draft0001
Revises: w1k2ord3lvl4
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision: str = "sd1draft0001"
down_revision: Union[str, None] = "w1k2ord3lvl4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DRAFTS = "seo_drafts"
_ANALYSES = "seo_draft_analyses"


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: CREATE TABLE IF NOT EXISTS is fine on
    # both, but the index creations below are not uniformly, and the app-profile suite runs
    # this on SQLite. Same idempotency guarantee, portable (MIGRATION_POLICY.md).
    bind = op.get_bind()
    existing = _tables(bind)

    if _DRAFTS not in existing:
        op.create_table(
            _DRAFTS,
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("title", sa.String(500), nullable=True),
            sa.Column("target_keywords", sa.JSON(), nullable=True),
            sa.Column("published_url", sa.String(), nullable=True, index=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if _ANALYSES not in existing:
        op.create_table(
            _ANALYSES,
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column(
                "draft_id", sa.String(), sa.ForeignKey("seo_drafts.id"), nullable=False, index=True
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("result", sa.JSON(), nullable=False),
            # Denormalised because comparing two analyses is the entire point of the table,
            # and unpacking JSON on every read makes the common operation the expensive one.
            sa.Column("word_count", sa.Integer(), nullable=True),
            sa.Column("readability", sa.Float(), nullable=True),
            sa.Column("search_score", sa.Float(), nullable=True),
            sa.Column("title_characters", sa.Integer(), nullable=True),
            sa.Column(
                "is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
                index=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)
    # Analyses first: they carry the foreign key.
    if _ANALYSES in existing:
        op.drop_table(_ANALYSES)
    if _DRAFTS in existing:
        op.drop_table(_DRAFTS)
