"""Add zone2_minutes to workouts.

Manual estimate of minutes spent in heart-rate Zone 2 during this workout.
User-entered, not auto-computed. Used by weekly-habits widget to track
'minutes Z2 cardio per week' goal.

Revision ID: x7l8m9n0o1p2
Revises: w6k7l8m9n0o1
Create Date: 2026-06-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "x7l8m9n0o1p2"
down_revision: Union[str, None] = "w6k7l8m9n0o1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "zone2_minutes"):
        op.add_column(
            "workouts",
            sa.Column("zone2_minutes", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("workouts", "zone2_minutes"):
        op.drop_column("workouts", "zone2_minutes")
