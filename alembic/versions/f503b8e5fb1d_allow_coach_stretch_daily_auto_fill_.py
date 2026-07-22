"""allow_coach_stretch_daily_auto_fill_source

Revision ID: f503b8e5fb1d
Revises: 3e1c0945a812
Create Date: 2026-07-20

Adds ``coach.stretch_daily`` to habits.auto_fill_source check so coach can
identify the Daily stretch habit (identity key; no workout autofill).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f503b8e5fb1d"
down_revision: Union[str, Sequence[str], None] = "3e1c0945a812"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km',"
    "'coach.stretch_daily')"
)
_OLD = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km')"
)


def upgrade() -> None:
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_NEW})"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE habits SET auto_fill_source = NULL "
        "WHERE auto_fill_source = 'coach.stretch_daily'"
    )
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_OLD})"
    )
