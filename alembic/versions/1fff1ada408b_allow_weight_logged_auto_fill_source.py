"""allow_weight_logged_auto_fill_source

Revision ID: 1fff1ada408b
Revises: a87e213dedbb
Create Date: 2026-07-30 22:29:00.627282

Adds ``weight.logged`` to the habits.auto_fill_source check constraint so the
weigh-in habit can tick itself off a weight entry. A number replied in Discord
IS the habit; asking for a second confirmation tap in the app is exactly the
kind of demand the lean program exists to remove.

Same drop/recreate shape as f503b8e5fb1d, which added ``coach.stretch_daily``.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '1fff1ada408b'
down_revision: Union[str, Sequence[str], None] = 'a87e213dedbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km',"
    "'coach.stretch_daily','weight.logged')"
)
_OLD = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km',"
    "'coach.stretch_daily')"
)


def upgrade() -> None:
    """Allow weight.logged as an auto_fill_source."""
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_NEW})"
    )


def downgrade() -> None:
    """Drop weight.logged, clearing any habit still using it."""
    op.execute(
        "UPDATE habits SET auto_fill_source = NULL "
        "WHERE auto_fill_source = 'weight.logged'"
    )
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_OLD})"
    )
