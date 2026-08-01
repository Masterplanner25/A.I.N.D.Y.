"""add ripple_content_sources (rippletrace published-content supply)

RippleTrace's drop points describe content you published on an external platform, and
until now the only way to create one was to type it in. This table holds a recurring
supply instead: a feed (RSS/Atom) the user publishes to, polled on a schedule, with
every new entry becoming a drop point.

``etag``/``last_modified`` support conditional GETs so an unchanged feed costs one
cheap request. The unique constraint on (user_id, feed_url) makes re-registering the
same feed a no-op rather than a duplicate supply.

Additive + guarded (inspector table/index checks) so it is idempotent on existing and
fresh databases alike.

Revision ID: c7d8e9f0a1b2
Revises: bb22cc33dd44
Create Date: 2026-08-01 12:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "bb22cc33dd44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ripple_content_sources"
_INDEXES = (
    ("ix_ripple_content_sources_id", "id"),
    ("ix_ripple_content_sources_user_id", "user_id"),
    ("ix_ripple_content_sources_feed_url", "feed_url"),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _TABLE not in insp.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("feed_url", sa.String(), nullable=False),
            sa.Column("site_url", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("platform", sa.String(), nullable=True),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="feed"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=32), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_entry_count", sa.Integer(), nullable=True),
            sa.Column("ingested_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("etag", sa.String(), nullable=True),
            sa.Column("last_modified", sa.String(), nullable=True),
            sa.UniqueConstraint(
                "user_id", "feed_url", name="uq_ripple_content_sources_user_feed"
            ),
        )

    existing = {ix["name"] for ix in inspect(bind).get_indexes(_TABLE)}
    for index_name, column in _INDEXES:
        if index_name not in existing:
            op.create_index(index_name, _TABLE, [column], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _TABLE not in insp.get_table_names():
        return
    existing = {ix["name"] for ix in insp.get_indexes(_TABLE)}
    for index_name, _ in _INDEXES:
        if index_name in existing:
            op.drop_index(index_name, table_name=_TABLE)
    op.drop_table(_TABLE)
