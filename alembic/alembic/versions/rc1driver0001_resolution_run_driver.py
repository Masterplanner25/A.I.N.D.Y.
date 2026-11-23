"""Resolution runs say who answers them: the Python tick or the Nodus workflow (FR-55)

`resolution_check_v1.nd` answers a check in batches and sleeps between them (runtime 2.39.0). The
tick leaves a check alone while the workflow's flow run is alive, so each run records its driver and
that flow run's id. Two nullable columns, additive and guarded, like every app migration.

Revision ID: rc1driver0001
Revises: dt1directing0001
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "rc1driver0001"
down_revision: Union[str, None] = "dt1directing0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("driver", sa.String(16)),
    ("driver_run_id", sa.String()),
)


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "resolution_runs" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("resolution_runs")}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column("resolution_runs", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "resolution_runs" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("resolution_runs")}
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("resolution_runs", name)
