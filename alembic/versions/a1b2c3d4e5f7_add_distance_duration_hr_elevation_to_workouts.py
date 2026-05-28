"""add distance, duration, heart rate, and elevation to workouts

Revision ID: a1b2c3d4e5f7
Revises: 319a0c74a6eb
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from helpers import column_exists

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "319a0c74a6eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "distance_km"):
        op.add_column("workouts", sa.Column("distance_km", sa.Numeric(7, 3), nullable=True))

    if not column_exists("workouts", "duration_seconds"):
        op.add_column("workouts", sa.Column("duration_seconds", sa.Integer(), nullable=True))

    if not column_exists("workouts", "avg_hr"):
        op.add_column("workouts", sa.Column("avg_hr", sa.Integer(), nullable=True))

    if not column_exists("workouts", "max_hr"):
        op.add_column("workouts", sa.Column("max_hr", sa.Integer(), nullable=True))

    if not column_exists("workouts", "elevation_m"):
        op.add_column("workouts", sa.Column("elevation_m", sa.Integer(), nullable=True))

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workouts'
                  AND constraint_name = 'ck_workouts_distance_non_negative'
            ) THEN
                ALTER TABLE workouts
                ADD CONSTRAINT ck_workouts_distance_non_negative
                CHECK (distance_km IS NULL OR distance_km >= 0);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workouts'
                  AND constraint_name = 'ck_workouts_duration_non_negative'
            ) THEN
                ALTER TABLE workouts
                ADD CONSTRAINT ck_workouts_duration_non_negative
                CHECK (duration_seconds IS NULL OR duration_seconds >= 0);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workouts'
                  AND constraint_name = 'ck_workouts_avg_hr_range'
            ) THEN
                ALTER TABLE workouts
                ADD CONSTRAINT ck_workouts_avg_hr_range
                CHECK (avg_hr IS NULL OR (avg_hr >= 20 AND avg_hr <= 250));
            END IF;
        END $$
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workouts'
                  AND constraint_name = 'ck_workouts_max_hr_range'
            ) THEN
                ALTER TABLE workouts
                ADD CONSTRAINT ck_workouts_max_hr_range
                CHECK (max_hr IS NULL OR (max_hr >= 20 AND max_hr <= 250));
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_max_hr_range")
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_avg_hr_range")
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_duration_non_negative")
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_distance_non_negative")
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS elevation_m")
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS max_hr")
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS avg_hr")
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS duration_seconds")
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS distance_km")
