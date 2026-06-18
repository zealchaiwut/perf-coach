"""Add tss_method column to workouts table.

Stores the method string returned by compute_running_tss ('power', 'pace',
'hr', or 'none') alongside the TSS value. When a manual TSS overrides the
computed value, tss_method still reflects how TSS would be computed so the UI
can show the comparison. Idempotent.

Revision ID: kk1f2a3b4c5d
Revises: jj0e1f2a3b4c
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "kk1f2a3b4c5d"
down_revision: Union[str, None] = "jj0e1f2a3b4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "tss_method"):
        op.add_column(
            "workouts",
            sa.Column("tss_method", sa.String(20), nullable=True),
        )


def downgrade() -> None:
    if column_exists("workouts", "tss_method"):
        op.drop_column("workouts", "tss_method")
