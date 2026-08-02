"""add genesis_sessions.transcript (Genesis conversation history)

Genesis kept only `summarized_state` — six extracted fields — so each turn the model
received a compressed snapshot plus the new message and no dialogue. It could not
reference anything said earlier except through that compression, which is what made a
"strategic partner" behave like a form-filler with a chat interface.

This column holds the conversation: [{"role", "content", "at"}]. It also lets the client
rehydrate on refresh; previously the transcript lived in React state alone and a reload
replaced it with a synthetic one-line summary.

Additive + guarded (inspector has_column) so it is idempotent on existing and fresh
databases alike.

Revision ID: gx7transcript01
Revises: rt9mention0001
Create Date: 2026-08-02 09:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "gx7transcript01"
down_revision: Union[str, None] = "rt9mention0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "genesis_sessions"
_COLUMN = "transcript"


def _has_column(bind, table: str, column: str) -> bool:
    insp = inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in inspect(bind).get_table_names():
        return
    if not _has_column(bind, _TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
