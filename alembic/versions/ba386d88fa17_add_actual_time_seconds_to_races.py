"""Add actual_time_seconds column to races table (issue #706).

Adds the ``actual_time_seconds`` nullable integer column that stores the
recorded finish time for a completed race.  The upgrade is idempotent:
it is a no-op when the column already exists.

Revision ID: ba386d88fa17
Revises: 145b95d5baf0, d915ffcb4c0c
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "ba386d88fa17"
down_revision: Union[str, Sequence[str], None] = ("145b95d5baf0", "d915ffcb4c0c")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("races"):
        return
    if column_exists("races", "actual_time_seconds"):
        return

    op.add_column(
        "races",
        sa.Column("actual_time_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    if not table_exists("races"):
        return
    if not column_exists("races", "actual_time_seconds"):
        return

    op.drop_column("races", "actual_time_seconds")
