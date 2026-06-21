"""backfill raw strava workout_type to canonical

Older syncs wrote the RAW Strava sport_type into workouts.workout_type
(e.g. "Run", "Workout", "WeightTraining", "Ride") because reconcile.py did not
apply the type map. This one-time, idempotent data migration normalizes those
sync-created rows to our canonical lowercase types so the UI labels/strength
editor behave correctly. Scoped to Strava-sourced workouts so manually-entered
types ("Running"/"Strength"/etc.) are never touched.

Mapping mirrors workout_reconcile._WORKOUT_TYPE_MAP:
    Run -> run, Ride -> bike, WeightTraining -> strength, Workout -> strength

Revision ID: 7723c7298d4d
Revises: 932ba10c0d09
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7723c7298d4d'
down_revision: Union[str, Sequence[str], None] = '932ba10c0d09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MAP = {
    "Run": "run",
    "Ride": "bike",
    "WeightTraining": "strength",
    "Workout": "strength",
}


def upgrade() -> None:
    # raw/canonical are hardcoded constants (no user input), so inlining them
    # keeps the migration correct in both online and `--sql` offline modes.
    for raw, canonical in _MAP.items():
        op.execute(
            "UPDATE workouts SET workout_type = '{canonical}' "
            "WHERE workout_type = '{raw}' "
            "AND (source ILIKE '%strava%' OR strava_activity_pk IS NOT NULL)".format(
                canonical=canonical, raw=raw
            )
        )


def downgrade() -> None:
    # Not reversible: original raw strings are not recoverable per-row.
    pass
