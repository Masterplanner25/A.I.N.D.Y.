"""leadgen_results.segment_id — the market segment a lead was found inside

`MARKET_MODEL_SPEC.md` §5.4, phase B. A nullable soft reference (the segment is masterplan's table),
indexed because the learning close's suppression groups outcomes by it.

Revision ID: sg1leadseg0001
Revises: mk1market0001
Create Date: 2026-09-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "sg1leadseg0001"
down_revision: Union[str, None] = "mk1market0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Inspector-guarded (SQLite runs this too, MIGRATION_POLICY.md).
    inspector = inspect(op.get_bind())
    if "leadgen_results" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("leadgen_results")}
    if "segment_id" not in columns:
        op.add_column("leadgen_results", sa.Column("segment_id", sa.String(), nullable=True))
    indexes = {i["name"] for i in inspector.get_indexes("leadgen_results")}
    if "ix_leadgen_results_segment_id" not in indexes:
        op.create_index("ix_leadgen_results_segment_id", "leadgen_results", ["segment_id"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "leadgen_results" not in inspector.get_table_names():
        return
    if "ix_leadgen_results_segment_id" in {i["name"] for i in inspector.get_indexes("leadgen_results")}:
        op.drop_index("ix_leadgen_results_segment_id", table_name="leadgen_results")
    if "segment_id" in {c["name"] for c in inspector.get_columns("leadgen_results")}:
        op.drop_column("leadgen_results", "segment_id")
