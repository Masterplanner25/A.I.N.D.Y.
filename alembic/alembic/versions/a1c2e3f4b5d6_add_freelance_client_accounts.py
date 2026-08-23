"""add_freelance_client_accounts

Phase 1 of the Freelancing evolution (docs/domains/FREELANCING_SYSTEM.md): add the
`freelance_client_accounts` table and a `client_id` link on `freelance_orders`
so leads, clients, and orders form one lead -> client -> order lineage.

All operations are guarded (IF NOT EXISTS semantics via the inspector) so the
migration is idempotent, consistent with the app/runtime migration rule.

Revision ID: a1c2e3f4b5d6
Revises: i2j3k4l5m6n7
Create Date: 2026-06-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a1c2e3f4b5d6"
down_revision: Union[str, None] = "i2j3k4l5m6n7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("freelance_client_accounts"):
        op.create_table(
            "freelance_client_accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("company", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("lead_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("freelance_client_accounts")} \
        if inspector.has_table("freelance_client_accounts") else set()
    if "ix_freelance_client_accounts_id" not in existing_indexes:
        op.create_index(op.f("ix_freelance_client_accounts_id"), "freelance_client_accounts", ["id"], unique=False)
    if "ix_freelance_client_accounts_user_id" not in existing_indexes:
        op.create_index(op.f("ix_freelance_client_accounts_user_id"), "freelance_client_accounts", ["user_id"], unique=False)
    if "ix_freelance_client_accounts_email" not in existing_indexes:
        op.create_index(op.f("ix_freelance_client_accounts_email"), "freelance_client_accounts", ["email"], unique=False)
    if "ix_freelance_client_accounts_lead_id" not in existing_indexes:
        op.create_index(op.f("ix_freelance_client_accounts_lead_id"), "freelance_client_accounts", ["lead_id"], unique=False)
    if "ux_freelance_client_accounts_user_email" not in existing_indexes:
        op.create_index(
            "ux_freelance_client_accounts_user_email",
            "freelance_client_accounts",
            ["user_id", "email"],
            unique=True,
        )

    order_columns = {c["name"] for c in inspector.get_columns("freelance_orders")}
    if "client_id" not in order_columns:
        op.add_column("freelance_orders", sa.Column("client_id", sa.Integer(), nullable=True))
        op.create_index(op.f("ix_freelance_orders_client_id"), "freelance_orders", ["client_id"], unique=False)
        # SQLite cannot add a foreign key via ALTER; only create the FK on engines
        # that support it (production is PostgreSQL).
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_freelance_orders_client_id",
                "freelance_orders",
                "freelance_client_accounts",
                ["client_id"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    order_columns = {c["name"] for c in inspector.get_columns("freelance_orders")}
    if "client_id" in order_columns:
        if bind.dialect.name != "sqlite":
            op.drop_constraint("fk_freelance_orders_client_id", "freelance_orders", type_="foreignkey")
        op.drop_index(op.f("ix_freelance_orders_client_id"), table_name="freelance_orders")
        op.drop_column("freelance_orders", "client_id")

    if inspector.has_table("freelance_client_accounts"):
        op.drop_table("freelance_client_accounts")
