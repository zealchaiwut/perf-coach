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

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Fix workouts.user_id FK: drop NO ACTION fk, recreate with CASCADE ---
    op.drop_constraint("workouts_user_id_fkey", "workouts", type_="foreignkey")
    op.create_foreign_key(
        "workouts_user_id_fkey",
        "workouts",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- Fix workout_exercises.workout_id FK: drop NO ACTION, recreate with CASCADE ---
    op.drop_constraint("workout_exercises_workout_id_fkey", "workout_exercises", type_="foreignkey")
    op.create_foreign_key(
        "workout_exercises_workout_id_fkey",
        "workout_exercises",
        "workouts",
        ["workout_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- Clean up any existing data that would violate the CHECK constraints ---
    # Previous test runs may have inserted rows with sets=0 or rpe out of range.
    # NULL-out invalid sets values (sets=0 is invalid; NULL means "not applicable").
    op.execute("UPDATE workout_exercises SET sets = NULL WHERE sets IS NOT NULL AND sets <= 0")
    # NULL-out invalid rpe values (outside 1-10 range).
    op.execute("UPDATE workout_exercises SET rpe = NULL WHERE rpe IS NOT NULL AND (rpe < 1 OR rpe > 10)")

    # --- Add CHECK constraints on workout_exercises (idempotent) ---
    # Use DO blocks so we don't fail if constraints already exist (e.g. fresh DB
    # where the inline CheckConstraint in op.create_table actually worked).
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
    # Use raw SQL for the DESC index to avoid dialect-specific op.create_index quirks
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workouts_user_date "
        "ON workouts (user_id, workout_date DESC)"
    )
    op.create_index(
        "ix_workout_exercises_workout_order",
        "workout_exercises",
        ["workout_id", "display_order"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_workout_exercises_workout_order", table_name="workout_exercises")
    op.execute("DROP INDEX IF EXISTS ix_workouts_user_date")

    # Drop CHECK constraints
    op.execute("ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS ck_workout_exercises_rpe_range")
    op.execute("ALTER TABLE workout_exercises DROP CONSTRAINT IF EXISTS ck_workout_exercises_sets_positive")

    # Revert FKs back to NO ACTION (default)
    op.drop_constraint("workout_exercises_workout_id_fkey", "workout_exercises", type_="foreignkey")
    op.create_foreign_key(
        "workout_exercises_workout_id_fkey",
        "workout_exercises",
        "workouts",
        ["workout_id"],
        ["id"],
    )

    op.drop_constraint("workouts_user_id_fkey", "workouts", type_="foreignkey")
    op.create_foreign_key(
        "workouts_user_id_fkey",
        "workouts",
        "users",
        ["user_id"],
        ["id"],
    )
