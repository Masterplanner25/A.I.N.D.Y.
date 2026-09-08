"""add pings.verification — a ping records a page about the same subject, not one that cites you

`RIPPLE-PINGS-NOT-ECHOES-1` / `docs/verification/DEFECT_RIPPLE_PINGS_ARE_NOT_ECHOES.md`.

RippleTrace's detection searches for a drop point's URL plus its distinctive title as an exact
phrase. The method is right; the provider is an **answer engine**, which returns the sources it
used to answer rather than pages containing the phrase. Measured on the live corpus 2026-09-07:
**1 of 256 pings pointed at a URL plausibly connected to the author**, and `openai.com` was the
most common "platform that echoed you" — 36 times.

★ **The default is `unverified`, and that is the point of this revision.** Every existing row was
recorded without anyone looking at the page, so `unverified` is the true statement about it. The
alternative — deleting the 256 rows — would silently rewrite history that `influence_graph`,
`causal_engine` and `strategy_engine` have already reasoned over, which is its own defect. They
are correctly-recorded answers to a different question; labelling them is the honest act.

Scoring counts `verified` alone, so this revision has an immediate and intended consequence:
**every narrative/velocity/spread score falls to zero until detection re-runs with verification
on.** That is the correct state. A score of 0 that means "nothing confirmed" is better than a
score of 24.5 that means "a search returned nine topically-related pages".

Revision ID: pv1verify0001
Revises: sl1strategy001
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "pv1verify0001"
down_revision: Union[str, None] = "sl1strategy001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "pings"


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Inspector-guarded rather than raw IF NOT EXISTS: ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    # is PostgreSQL-only and the app-profile suite runs this on SQLite (MIGRATION_POLICY.md).
    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    if not _has_column(inspector, _TABLE, "verification"):
        op.add_column(
            _TABLE,
            sa.Column(
                "verification",
                sa.String(16),
                nullable=False,
                # Honest about every row that predates the check.
                server_default="unverified",
            ),
        )
        op.create_index("ix_pings_verification", _TABLE, ["verification"])
    if not _has_column(inspector, _TABLE, "verification_note"):
        op.add_column(_TABLE, sa.Column("verification_note", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _has_column(inspector, _TABLE, "verification_note"):
        op.drop_column(_TABLE, "verification_note")
    if _has_column(inspector, _TABLE, "verification"):
        op.drop_index("ix_pings_verification", table_name=_TABLE)
        op.drop_column(_TABLE, "verification")
