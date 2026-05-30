"""rename workout_exercises.weight -> weight_kg (Numeric) and reps VARCHAR -> Integer

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-05-30 00:00:00.000000

The original create_workout_exercises migration named the column 'weight' (VARCHAR)
and 'reps' (VARCHAR). The ORM model and seed script expect 'weight_kg' (Numeric)
and 'reps' (Integer). This migration aligns the DB schema with the model.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from helpers import column_exists

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename weight (VARCHAR) -> weight_kg (Numeric(6,2))
    if column_exists("workout_exercises", "weight") and not column_exists("workout_exercises", "weight_kg"):
        op.execute(
            "ALTER TABLE workout_exercises RENAME COLUMN weight TO weight_kg"
        )
        op.execute(
            "ALTER TABLE workout_exercises ALTER COLUMN weight_kg TYPE NUMERIC(6,2)"
            " USING CASE WHEN weight_kg ~ '^[0-9]+(\\.[0-9]+)?$' THEN weight_kg::NUMERIC(6,2) ELSE NULL END"
        )
    elif not column_exists("workout_exercises", "weight_kg"):
        op.add_column(
            "workout_exercises",
            sa.Column("weight_kg", sa.Numeric(6, 2), nullable=True),
        )

    # Fix reps: VARCHAR(50) -> Integer
    if column_exists("workout_exercises", "reps"):
        op.execute(
            "ALTER TABLE workout_exercises ALTER COLUMN reps TYPE INTEGER"
            " USING CASE WHEN reps ~ '^[0-9]+$' THEN reps::INTEGER ELSE NULL END"
        )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE workout_exercises ALTER COLUMN reps TYPE VARCHAR(50) USING reps::VARCHAR"
    )
    if column_exists("workout_exercises", "weight_kg") and not column_exists("workout_exercises", "weight"):
        op.execute(
            "ALTER TABLE workout_exercises RENAME COLUMN weight_kg TO weight"
        )
        op.execute(
            "ALTER TABLE workout_exercises ALTER COLUMN weight TYPE VARCHAR(50) USING weight::VARCHAR"
        )
