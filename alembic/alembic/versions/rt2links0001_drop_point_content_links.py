"""Drop points keep the links the writer made

ARTICLE_ANSWERS_SPEC §3, decision 2 (owner, 2026-11-08): keep link targets for every platform. A
piece's text is stored as plain text (`content_archive.to_text`), which strips HTML and the `href`s
with it, so the 46 Substack and 19 Medium pieces had lost every link. `content_links` keeps them from
the raw body when a piece is fetched. NULL means not read yet; an empty list means it links to nothing.

Additive and guarded, like every app migration.

Revision ID: rt2links0001
Revises: fl1metrics0001
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "rt2links0001"
down_revision: Union[str, None] = "fl1metrics0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "drop_points" not in set(inspector.get_table_names()):
        return
    if "content_links" not in {c["name"] for c in inspector.get_columns("drop_points")}:
        op.add_column("drop_points", sa.Column("content_links", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "drop_points" not in set(inspector.get_table_names()):
        return
    if "content_links" in {c["name"] for c in inspector.get_columns("drop_points")}:
        op.drop_column("drop_points", "content_links")
