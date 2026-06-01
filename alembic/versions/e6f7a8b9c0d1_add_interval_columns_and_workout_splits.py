"""add interval columns to workout_exercises and create workout_splits table

Revision ID: e6f7a8b9c0d1
Revises: b3c4d5e6f7a8
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from helpers import column_exists, table_exists

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Add interval columns to workout_exercises ─────────────────────────────
    if not column_exists("workout_exercises", "distance_km"):
        op.add_column("workout_exercises", sa.Column("distance_km", sa.Numeric(8, 3), nullable=True))

    if not column_exists("workout_exercises", "duration_seconds"):
        op.add_column("workout_exercises", sa.Column("duration_seconds", sa.Integer(), nullable=True))

    if not column_exists("workout_exercises", "avg_hr"):
        op.add_column("workout_exercises", sa.Column("avg_hr", sa.Integer(), nullable=True))

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workout_exercises'
                  AND constraint_name = 'ck_workout_exercises_distance_non_negative'
            ) THEN
                ALTER TABLE workout_exercises
                ADD CONSTRAINT ck_workout_exercises_distance_non_negative
                CHECK (distance_km IS NULL OR distance_km >= 0);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workout_exercises'
                  AND constraint_name = 'ck_workout_exercises_duration_non_negative'
            ) THEN
                ALTER TABLE workout_exercises
                ADD CONSTRAINT ck_workout_exercises_duration_non_negative
                CHECK (duration_seconds IS NULL OR duration_seconds >= 0);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workout_exercises'
                  AND constraint_name = 'ck_workout_exercises_avg_hr_range'
            ) THEN
                ALTER TABLE workout_exercises
                ADD CONSTRAINT ck_workout_exercises_avg_hr_range
                CHECK (avg_hr IS NULL OR (avg_hr >= 20 AND avg_hr <= 250));
            END IF;
        END $$
    """)

    # ── Create workout_splits table ───────────────────────────────────────────
    if not table_exists("workout_splits"):
        op.create_table(
            "workout_splits",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("workout_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("split_index", sa.Integer(), nullable=False),
            sa.Column("distance_km", sa.Numeric(6, 3), nullable=False),
            sa.Column("duration_seconds", sa.Integer(), nullable=False),
            sa.Column("avg_hr", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("workout_id", "split_index", name="uq_workout_splits_workout_split_index"),
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workout_splits")
    op.execute("ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS ck_workout_exercises_avg_hr_range")
    op.execute("ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS ck_workout_exercises_duration_non_negative")
    op.execute("ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS ck_workout_exercises_distance_non_negative")
    op.execute("ALTER TABLE workout_exercises DROP COLUMN IF EXISTS avg_hr")
    op.execute("ALTER TABLE workout_exercises DROP COLUMN IF EXISTS duration_seconds")
    op.execute("ALTER TABLE workout_exercises DROP COLUMN IF EXISTS distance_km")
