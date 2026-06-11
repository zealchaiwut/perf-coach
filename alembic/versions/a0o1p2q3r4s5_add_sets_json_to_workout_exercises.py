"""add sets_json to workout_exercises (per-set strength logging)

Revision ID: a0o1p2q3r4s5
Revises: z9n0o1p2q3r4
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from helpers import column_exists

revision: str = "a0o1p2q3r4s5"
down_revision: Union[str, None] = "z9n0o1p2q3r4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSON array of per-set detail (weight, reps, rpe, rest, set_type) for the
    # strength exercise builder. Summary columns (sets/reps/weight_kg) stay for
    # backward compatibility + PR detection.
    if not column_exists("workout_exercises", "sets_json"):
        op.add_column(
            "workout_exercises",
            sa.Column("sets_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("workout_exercises", "sets_json"):
        op.drop_column("workout_exercises", "sets_json")
