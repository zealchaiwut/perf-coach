"""add_fuelled_to_workouts_and_long_run_fuel_habit

Revision ID: 37e30b89c6cd
Revises: c76739716276
Create Date: 2026-07-30 23:09:03.030878

Two changes for the lean program's third goal habit (long-run fuelling):

1. ``workouts.fuelled`` — did this session take on fuel (gels/drink)? Nullable
   because it is unknown for every workout logged before this column existed,
   and "unknown" must not read as "no". Only a long run's value is ever
   consulted.
2. ``long_run.fuelled`` joins the habits.auto_fill_source check constraint so
   the habit can tick itself off a fuelled long run rather than asking for a tap
   the athlete already earned.

Uses ADD COLUMN IF NOT EXISTS rather than the helpers.column_exists guard used
elsewhere: it is idempotent at the SQL level and satisfies the repo's
add-column-guard convention check without a Python round trip.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '37e30b89c6cd'
down_revision: Union[str, Sequence[str], None] = 'c76739716276'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km',"
    "'coach.stretch_daily','weight.logged','long_run.fuelled')"
)
_OLD = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km',"
    "'coach.stretch_daily','weight.logged')"
)


def upgrade() -> None:
    """Add workouts.fuelled and allow the long_run.fuelled autofill source."""
    op.execute("ALTER TABLE workouts ADD COLUMN IF NOT EXISTS fuelled BOOLEAN")
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_NEW})"
    )


def downgrade() -> None:
    """Drop workouts.fuelled and the long_run.fuelled source."""
    op.execute(
        "UPDATE habits SET auto_fill_source = NULL "
        "WHERE auto_fill_source = 'long_run.fuelled'"
    )
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_OLD})"
    )
    op.execute("ALTER TABLE workouts DROP COLUMN IF EXISTS fuelled")
