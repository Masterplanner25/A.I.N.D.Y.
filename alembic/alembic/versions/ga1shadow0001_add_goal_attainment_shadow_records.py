"""add goal_attainment_shadow_records — attainment next to the live plan-progress score

`MASTERPLAN_GOAL_ATTAINMENT_SPEC` §6 Phase 2, built 2026-09-11 once attribution existed
(`STRATEGY_LAYER_SPEC` §5b, #335). Each canonical score computation, when
`AINDY_MASTERPLAN_GOAL_ATTAINMENT_SHADOW` is on, records what `masterplan_progress` *would*
have been with attainment blended in, next to what it was. Drives nothing; observability for
the soak. Same shape and same guards as `three_axis_shadow_records` (d7e8f9a0b1c2).

Inspector-guarded; the users FK is only added on engines that support ALTER-add-FK
(production is PostgreSQL; SQLite skips it). Downgrade drops the table — the replay guard
(scripts/replay_app_migrations.py) requires it to.

Revision ID: ga1shadow0001
Revises: pd1dismiss001
Create Date: 2026-09-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "ga1shadow0001"
down_revision: Union[str, None] = "pd1dismiss001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "goal_attainment_shadow_records"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("masterplan_id", sa.Integer(), nullable=True),
            sa.Column("live_score", sa.Float(), nullable=True),
            sa.Column("shadow_score", sa.Float(), nullable=True),
            sa.Column("attainment_pct", sa.Float(), nullable=True),
            sa.Column("completion_pct", sa.Float(), nullable=True),
            sa.Column("schedule_score", sa.Float(), nullable=True),
            sa.Column("hours_completed", sa.Float(), nullable=True),
            sa.Column("hours_total", sa.Float(), nullable=True),
            sa.Column("objectives_measured", sa.Integer(), nullable=True),
            sa.Column("objectives", sa.JSON(), nullable=True),
            sa.Column("trigger_event", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            *([] if is_sqlite else [sa.ForeignKeyConstraint(["user_id"], ["users.id"])]),
        )

    indexes = (
        {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        if inspector.has_table(_TABLE)
        else set()
    )
    for col in ("user_id", "masterplan_id", "trigger_event", "created_at"):
        ix_name = f"ix_{_TABLE}_{col}"
        if ix_name not in indexes:
            op.create_index(op.f(ix_name), _TABLE, [col], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(_TABLE):
        op.drop_table(_TABLE)
