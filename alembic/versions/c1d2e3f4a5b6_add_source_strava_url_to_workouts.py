"""add source and strava_activity_url columns to workouts

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f7
Create Date: 2026-05-29 00:00:00.000000

source tracks whether a workout came from Strava or was entered manually.
strava_activity_url stores the deep-link to the activity on Strava so the
detail panel can offer an "Open in Strava" button.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "source"):
        op.add_column("workouts", sa.Column("source", sa.String(20), nullable=True))

    if not column_exists("workouts", "strava_activity_url"):
        op.add_column("workouts", sa.Column("strava_activity_url", sa.Text(), nullable=True))

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workouts'
                  AND constraint_name = 'ck_workouts_source_values'
            ) THEN
                ALTER TABLE workouts
                ADD CONSTRAINT ck_workouts_source_values
                CHECK (source IS NULL OR source IN ('strava', 'manual'));
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_source_values")
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS strava_activity_url")
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS source")
