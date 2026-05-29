"""expand workout source constraint to allow stryd and compound source values

Revision ID: b3c4d5e6f7a8
Revises: d5e6f7a8b9c0
Create Date: 2026-05-29 00:00:00.000000

Stryd is a power-meter footpod that uploads to its own platform.  Workouts
imported from Stryd need source='stryd', and a single workout can carry both
Strava and Stryd data simultaneously (source='strava,stryd' or 'stryd,strava').
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED = "('manual', 'strava', 'stryd', 'strava,stryd', 'stryd,strava')"


def upgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_source_values")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workouts'
                  AND constraint_name = 'ck_workouts_source_values'
            ) THEN
                ALTER TABLE workouts
                ADD CONSTRAINT ck_workouts_source_values
                CHECK (source IS NULL OR source IN {_ALLOWED});
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_source_values")
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE workouts
            ADD CONSTRAINT ck_workouts_source_values
            CHECK (source IS NULL OR source IN ('strava', 'manual'));
        END $$
    """)
