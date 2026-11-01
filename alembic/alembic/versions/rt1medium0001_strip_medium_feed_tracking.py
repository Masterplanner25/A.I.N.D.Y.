"""Stored Medium links lose the feed's ``?source=rss…`` tag

Medium's feed links every piece as ``…?source=rss----<publication>---4``. It was stored as the
piece's URL and went into share drafts' links (2026-11-01). Ingest now drops it; this rewrites the
URLs already stored. **Only the URL changes**: each row keeps its id, which is still derived from
the tagged form (`legacy_drop_point_id_for`), so nothing that refers to it moves.

Revision ID: rt1medium0001
Revises: sd1share0001
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "rt1medium0001"
down_revision: Union[str, None] = "sd1share0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or "drop_points" not in inspect(bind).get_table_names():
        return
    # Medium's feed URLs carry only this one parameter, so the whole query goes.
    op.execute(
        r"""
        UPDATE drop_points
        SET url = regexp_replace(url, '\?source=[^&#]*$', '')
        WHERE url ~ '^https?://([a-z0-9-]+\.)*medium\.com/[^?]*\?source=[^&#]*$'
        """
    )


def downgrade() -> None:
    # The tag is a referrer marker; nothing reads it, so there is nothing to restore.
    pass
