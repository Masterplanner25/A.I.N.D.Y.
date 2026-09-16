"""add leadgen_results.contact_email and lead_actions.recipient / sent_at — the send gets a recipient

The Search Execution Layer's `email` channel was "intentionally not wired" since it shipped
(BUILD_PLAN "Search's real send"). The reason was never the send call — the runtime ships
`email_channel.send_email()` — it was that a `LeadGenResult` carries no address: company, url,
context, four scores. Nothing to send to.

Owner's decision 2026-09-16: recipients are entered by hand on the lead (no enrichment, no
scraping). `contact_email` is nullable and unset by discovery; only a lead with one can be sent
to, and the action records what was sent where (`recipient`, `sent_at`) so "outreach can't be
un-sent" has a row to point at.

Revision ID: lc1contact001
Revises: ga1shadow0001
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "lc1contact001"
down_revision: Union[str, None] = "ga1shadow0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


_COLUMNS = (
    ("leadgen_results", "contact_email", lambda: sa.Column("contact_email", sa.String(), nullable=True)),
    ("lead_actions", "recipient", lambda: sa.Column("recipient", sa.String(), nullable=True)),
    ("lead_actions", "sent_at", lambda: sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True)),
)


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    # is PostgreSQL-only and the app-profile suite runs this on SQLite (MIGRATION_POLICY.md).
    # All three nullable with no default on either side — the parity guard (Step 6) agrees.
    bind = op.get_bind()
    inspector = inspect(bind)
    for table, column, make in _COLUMNS:
        if table not in inspector.get_table_names():
            continue
        if not _has_column(inspector, table, column):
            op.add_column(table, make())


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table, column, _ in reversed(_COLUMNS):
        if _has_column(inspector, table, column):
            op.drop_column(table, column)
