"""add work_presence, resolution_runs, resolution_answers — the Resolution Check, phase A

`RESOLUTION_CHECK_SPEC.md`. Where each Work is on the web and what it says about itself there
(declared by the owner, a control and a set of connections), and the runs and answers of a check
that asks answer engines about the owner's entities and scores them against what the owner confirmed.
Three new tables; nothing existing is altered (the new Work kinds and relation are vocabulary, held in
code, and fit the existing columns).

Revision ID: rc1resolve0001
Revises: wk2success0001
Create Date: 2026-09-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "rc1resolve0001"
down_revision: Union[str, None] = "wk2success0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user_id():
    return sa.Column("user_id", postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
                     sa.ForeignKey("users.id"), nullable=False, index=True)


def _stamp(name: str = "created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # Inspector-guarded (SQLite runs this too); only the timestamps carry server defaults.
    existing = set(inspect(op.get_bind()).get_table_names())
    if "work_presence" not in existing:
        op.create_table(
            "work_presence",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id(),
            sa.Column("work_id", sa.String(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("platform", sa.String(64), nullable=False),
            sa.Column("url", sa.String(500), nullable=True),
            sa.Column("self_description", sa.Text(), nullable=True),
            _stamp(),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "resolution_runs" not in existing:
        op.create_table(
            "resolution_runs",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            _user_id(),
            sa.Column("scope", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, index=True),
            sa.Column("questions", sa.JSON(), nullable=False),
            sa.Column("engines", sa.JSON(), nullable=False),
            sa.Column("calls", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            _stamp(),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "resolution_answers" not in existing:
        op.create_table(
            "resolution_answers",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("resolution_runs.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            _user_id(),
            sa.Column("question_key", sa.String(200), nullable=False),
            sa.Column("engine", sa.String(64), nullable=False),
            sa.Column("answer", sa.Text(), nullable=True),
            sa.Column("citations", sa.JSON(), nullable=True),
            sa.Column("judgement", sa.JSON(), nullable=True),
            sa.Column("scores", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            _stamp(),
        )


def downgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    for table in ("resolution_answers", "resolution_runs", "work_presence"):
        if table in existing:
            op.drop_table(table)
