"""add source FK columns and workout merge support to workouts

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-30 00:00:00.000000

Adds strava_activity_pk, stryd_activity_pk, manual_overrides, start_time columns
to the workouts table. Also expands the source check constraint to include 'both'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from helpers import column_exists, fk_exists

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE_CONSTRAINT = "ck_workouts_source_values"
_ALLOWED = "('manual', 'strava', 'stryd', 'strava,stryd', 'stryd,strava', 'both')"


def upgrade() -> None:
    if not column_exists("workouts", "strava_activity_pk"):
        op.add_column(
            "workouts",
            sa.Column("strava_activity_pk", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not fk_exists("workouts", "fk_workouts_strava_activity_pk"):
        op.create_foreign_key(
            "fk_workouts_strava_activity_pk",
            "workouts",
            "strava_activities",
            ["strava_activity_pk"],
            ["id"],
            ondelete="SET NULL",
        )

    if not column_exists("workouts", "stryd_activity_pk"):
        op.add_column(
            "workouts",
            sa.Column("stryd_activity_pk", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not fk_exists("workouts", "fk_workouts_stryd_activity_pk"):
        op.create_foreign_key(
            "fk_workouts_stryd_activity_pk",
            "workouts",
            "stryd_activities",
            ["stryd_activity_pk"],
            ["id"],
            ondelete="SET NULL",
        )

    if not column_exists("workouts", "manual_overrides"):
        op.add_column(
            "workouts",
            sa.Column("manual_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )

    if not column_exists("workouts", "start_time"):
        op.add_column(
            "workouts",
            sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        )

    op.execute(f"ALTER TABLE workouts DROP CONSTRAINT IF EXISTS {_SOURCE_CONSTRAINT}")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'workouts'
                  AND constraint_name = '{_SOURCE_CONSTRAINT}'
            ) THEN
                ALTER TABLE workouts
                ADD CONSTRAINT {_SOURCE_CONSTRAINT}
                CHECK (source IS NULL OR source IN {_ALLOWED});
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute(f"ALTER TABLE workouts DROP CONSTRAINT IF EXISTS {_SOURCE_CONSTRAINT}")
    op.execute("""
        ALTER TABLE workouts
        ADD CONSTRAINT ck_workouts_source_values
        CHECK (source IS NULL OR source IN ('manual', 'strava', 'stryd', 'strava,stryd', 'stryd,strava'))
    """)

    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS fk_workouts_strava_activity_pk")
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS fk_workouts_stryd_activity_pk")

    if column_exists("workouts", "start_time"):
        op.drop_column("workouts", "start_time")
    if column_exists("workouts", "manual_overrides"):
        op.drop_column("workouts", "manual_overrides")
    if column_exists("workouts", "stryd_activity_pk"):
        op.drop_column("workouts", "stryd_activity_pk")
    if column_exists("workouts", "strava_activity_pk"):
        op.drop_column("workouts", "strava_activity_pk")
