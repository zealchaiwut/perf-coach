"""Add temperature_c and humidity_pct to workouts for heat correction (issue #1168).

Revision ID: 1895a1396795
Revises: 4ea6071056c8
Create Date: 2026-07-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "1895a1396795"
down_revision: Union[str, Sequence[str], None] = "4ea6071056c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "temperature_c"):
        op.add_column(
            "workouts",
            sa.Column("temperature_c", sa.Float(), nullable=True),
        )
    if not column_exists("workouts", "humidity_pct"):
        op.add_column(
            "workouts",
            sa.Column("humidity_pct", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("workouts", "humidity_pct"):
        op.drop_column("workouts", "humidity_pct")
    if column_exists("workouts", "temperature_c"):
        op.drop_column("workouts", "temperature_c")
