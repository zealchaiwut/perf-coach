"""fix fk cascade, check constraints, and indexes on workout tables

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-27 00:00:02.000000

The previous two migrations (c3d4e5f6a7b8, d4e5f6a7b8c9) used
op.create_table() with inline ForeignKeyConstraint(ondelete="CASCADE")
and inline CheckConstraint, but Neon PostgreSQL ignored those options
and created the FKs as NO ACTION with no check constraints and no indexes.

This migration explicitly:
1. Drops the auto-generated FKs (NO ACTION) and recreates them with CASCADE
2. Adds the CHECK constraints for sets > 0 and rpe between 1-10
3. Adds the composite indexes required by the spec

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Fix workouts.user_id FK: drop (if exists) and recreate with CASCADE ---
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE workouts DROP CONSTRAINT IF EXISTS workouts_user_id_fkey;
            ALTER TABLE workouts ADD CONSTRAINT workouts_user_id_fkey
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    # --- Fix workout_exercises.workout_id FK: drop (if exists) and recreate with CASCADE ---
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS workout_exercises_workout_id_fkey;
            ALTER TABLE workout_exercises ADD CONSTRAINT workout_exercises_workout_id_fkey
                FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    # --- Clean up any existing data that would violate the CHECK constraints ---
    op.execute("UPDATE workout_exercises SET sets = NULL WHERE sets IS NOT NULL AND sets <= 0")
    op.execute("UPDATE workout_exercises SET rpe = NULL WHERE rpe IS NOT NULL AND (rpe < 1 OR rpe > 10)")

    # --- Add CHECK constraints on workout_exercises (idempotent) ---
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workout_exercises'
                  AND constraint_name = 'ck_workout_exercises_sets_positive'
            ) THEN
                ALTER TABLE workout_exercises ADD CONSTRAINT ck_workout_exercises_sets_positive
                CHECK (sets IS NULL OR sets > 0);
            END IF;
        END
        $$
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workout_exercises'
                  AND constraint_name = 'ck_workout_exercises_rpe_range'
            ) THEN
                ALTER TABLE workout_exercises ADD CONSTRAINT ck_workout_exercises_rpe_range
                CHECK (rpe IS NULL OR (rpe >= 1 AND rpe <= 10));
            END IF;
        END
        $$
    """)

    # --- Add composite indexes ---
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workouts_user_date "
        "ON workouts (user_id, workout_date DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workout_exercises_workout_order "
        "ON workout_exercises (workout_id, display_order)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_workout_exercises_workout_order")
    op.execute("DROP INDEX IF EXISTS ix_workouts_user_date")

    op.execute("ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS ck_workout_exercises_rpe_range")
    op.execute("ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS ck_workout_exercises_sets_positive")

    # Revert FKs back to NO ACTION (default)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS workout_exercises_workout_id_fkey;
            ALTER TABLE workout_exercises ADD CONSTRAINT workout_exercises_workout_id_fkey
                FOREIGN KEY (workout_id) REFERENCES workouts(id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE workouts DROP CONSTRAINT IF EXISTS workouts_user_id_fkey;
            ALTER TABLE workouts ADD CONSTRAINT workouts_user_id_fkey
                FOREIGN KEY (user_id) REFERENCES users(id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
