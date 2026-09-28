"""add works, work_links, work_objectives, work_revisions, work_proposal_dismissals — the Work model

`WORK_MODEL_SPEC.md` §3, phase A. What the owner has made (a Work: intent, never measurement), how
the works relate (six verbs), which plan objectives they serve, their history, and the proposals
the owner declined. Five new tables; nothing existing is altered. The link to a RippleTrace
container lives on `works.container_id` (a soft reference), so RippleTrace's table is untouched.

Revision ID: wk1work0001
Revises: sc1concl0001
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "wk1work0001"
down_revision: Union[str, None] = "sc1concl0001"
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


def _created_at(name: str = "created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: the app-profile suite runs migrations on
    # SQLite (MIGRATION_POLICY.md). Only the timestamps carry server defaults, matching the
    # models, so the schema-default parity guard agrees.
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())

    if "works" not in existing:
        op.create_table(
            "works",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id_column(),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("role", sa.String(24), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("started_on", sa.Date(), nullable=True),
            sa.Column("ended_on", sa.Date(), nullable=True),
            sa.Column("url", sa.String(500), nullable=True),
            sa.Column("declared_target", sa.Text(), nullable=True),
            sa.Column("container_id", sa.String(), nullable=True, index=True),
            sa.Column("provenance", sa.String(16), nullable=False),
            _created_at(),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "work_links" not in existing:
        op.create_table(
            "work_links",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id_column(),
            sa.Column("from_work_id", sa.String(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("to_work_id", sa.String(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("relation", sa.String(24), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            _created_at(),
        )

    if "work_objectives" not in existing:
        op.create_table(
            "work_objectives",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column("work_id", sa.String(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("objective_id", sa.String(), sa.ForeignKey("plan_objectives.id", ondelete="CASCADE"), nullable=False, index=True),
            _created_at(),
        )

    if "work_revisions" not in existing:
        op.create_table(
            "work_revisions",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column("work_id", sa.String(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("field", sa.String(32), nullable=False),
            sa.Column("old_value", sa.Text(), nullable=True),
            sa.Column("new_value", sa.Text(), nullable=True),
            _created_at("changed_at"),
        )

    if "work_proposal_dismissals" not in existing:
        op.create_table(
            "work_proposal_dismissals",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id_column(),
            sa.Column("proposal_key", sa.String(400), nullable=False, index=True),
            _created_at("dismissed_at"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in ("work_proposal_dismissals", "work_revisions", "work_objectives", "work_links", "works"):
        if table in existing:
            op.drop_table(table)
