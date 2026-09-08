"""add plan_objectives, plan_phases, plan_strategies and the task references

`STRATEGY_LAYER_SPEC.md` §8, step 1 of the migration shape. The layer already existed in this
system — it was stored as tasks. On the live plan, "tasks" 12–16 are the five Genesis phases
wearing task rows: never actionable, never completable, permanently `pending`.

★ **Additive and unread.** §8 is explicit that nothing may read `plan_phases` until the six live
rows have moved, or the plan briefly has five phases in one table and five phases-as-tasks in
another — the exact condition the spec complains about, added to rather than removed. This
revision creates the shape; a later, hand-written one moves the rows.

`plan_phases.depends_on_phase_id` exists from the start because the phase order is load-bearing:
the live chain 12→13→14→15→16 feeds `eta_service` → `critical_depth`, which sets a sequential
floor on the plan's ETA. Carried as an explicit edge rather than inferred from `ordinal`, so the
move cannot quietly lose it.

`tasks.strategy_id` / `tasks.phase_id` are plain indexed strings rather than foreign keys.
`tasks` is a core-domain table written by several paths, and an FK would make abandoning a
strategy a delete-ordering problem — while §6 Q4 requires the opposite: completed tasks stay
untouched, incomplete ones return to the plan unattached.

Revision ID: sl1strategy001
Revises: rc1container001
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision: str = "sl1strategy001"
down_revision: Union[str, None] = "rc1container001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OBJECTIVES = "plan_objectives"
_PHASES = "plan_phases"
_STRATEGIES = "plan_strategies"


def _uuid_col():
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: the app-profile suite runs migrations on
    # SQLite, where the PostgreSQL-only form is unavailable (MIGRATION_POLICY.md).
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    if _OBJECTIVES not in existing:
        op.create_table(
            _OBJECTIVES,
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column(
                "masterplan_id", sa.Integer(), sa.ForeignKey("master_plans.id"),
                nullable=False, index=True,
            ),
            sa.Column("user_id", _uuid_col(), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("intent", sa.Text(), nullable=True),
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if _PHASES not in existing:
        op.create_table(
            _PHASES,
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column(
                "masterplan_id", sa.Integer(), sa.ForeignKey("master_plans.id"),
                nullable=False, index=True,
            ),
            sa.Column("user_id", _uuid_col(), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_months", sa.Integer(), nullable=True),
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="pending", index=True
            ),
            # The phase order is load-bearing — see the module docstring.
            sa.Column(
                "depends_on_phase_id", sa.String(), sa.ForeignKey("plan_phases.id"),
                nullable=True, index=True,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if _STRATEGIES not in existing:
        op.create_table(
            _STRATEGIES,
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column(
                "masterplan_id", sa.Integer(), sa.ForeignKey("master_plans.id"),
                nullable=False, index=True,
            ),
            sa.Column("user_id", _uuid_col(), sa.ForeignKey("users.id"), nullable=True, index=True),
            # Ownership. Nullable because an emergent strategy may have no home objective yet,
            # and that case is what a *revise* is derived from.
            sa.Column(
                "objective_id", sa.String(), sa.ForeignKey("plan_objectives.id"),
                nullable=True, index=True,
            ),
            # Scheduling. Changing it is a refine, not a rewrite.
            sa.Column(
                "phase_id", sa.String(), sa.ForeignKey("plan_phases.id"),
                nullable=True, index=True,
            ),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "origin", sa.String(16), nullable=False, server_default="planned", index=True
            ),
            sa.Column(
                "status", sa.String(32), nullable=False, server_default="proposed", index=True
            ),
            # NULL for a displaced strategy, permanently: it was never tried, so there is
            # nothing to judge.
            sa.Column("outcome", sa.String(16), nullable=True, index=True),
            sa.Column("outcome_note", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("concluded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    inspector = inspect(bind)
    if not _has_column(inspector, "tasks", "strategy_id"):
        op.add_column("tasks", sa.Column("strategy_id", sa.String(), nullable=True))
        op.create_index("ix_tasks_strategy_id", "tasks", ["strategy_id"])
    if not _has_column(inspector, "tasks", "phase_id"):
        op.add_column("tasks", sa.Column("phase_id", sa.String(), nullable=True))
        op.create_index("ix_tasks_phase_id", "tasks", ["phase_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, "tasks", "phase_id"):
        op.drop_index("ix_tasks_phase_id", table_name="tasks")
        op.drop_column("tasks", "phase_id")
    if _has_column(inspector, "tasks", "strategy_id"):
        op.drop_index("ix_tasks_strategy_id", table_name="tasks")
        op.drop_column("tasks", "strategy_id")

    existing = set(inspect(bind).get_table_names())
    # Strategies first: they reference both of the others.
    for table in (_STRATEGIES, _PHASES, _OBJECTIVES):
        if table in existing:
            op.drop_table(table)
