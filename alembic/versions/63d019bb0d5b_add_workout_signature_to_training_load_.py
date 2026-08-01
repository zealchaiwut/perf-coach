"""add workout signature to training load snapshots

Found live: training_load_snapshots.tss_for_day was 0 or heavily
undercounted for 3 of the last 4 weeks on the real account, while CTL/ATL/TSB
are read exclusively from this cached table (coach_export.py's own docstring:
"the sole source every other consumer reads, no independent recompute"). Root
cause: get_snapshot_series()'s cache-hit check only treats a row as stale on
a formula_version or EWMA-calibration mismatch -- never when the underlying
workout data for that date changes after the row was cached. A snapshot
computed before that day's workout was synced/logged just sits there wrong
indefinitely; nothing currently forces a recompute.

This mirrors the exact bug class backend/main.py's _SUMMARY_CACHE already
solved with a signature check (_summary_signature: count/max(created_at)/
max(updated_at) over the user's workouts) -- same pattern, applied per
snapshot-date instead of globally, since CTL/ATL/TSB are keyed by date.

Adds a nullable workout_signature column: a row missing it (existing rows)
or whose stored value no longer matches that date's current workout
signature is now also treated as a cache miss by get_snapshot_series() and
recomputed. Existing rows are not backfilled here -- they simply lack a
signature to compare against, which get_snapshot_series() treats as stale on
next read (self-healing on the next read of that date range, not a bulk
recompute this migration would otherwise have to do live during a deploy).

Revision ID: 63d019bb0d5b
Revises: 6f945c183d82
Create Date: 2026-08-01 23:07:16.892279

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '63d019bb0d5b'
down_revision: Union[str, Sequence[str], None] = '6f945c183d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not table_exists("training_load_snapshots"):
        return
    if not column_exists("training_load_snapshots", "workout_signature"):
        op.add_column(
            "training_load_snapshots",
            sa.Column("workout_signature", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if not table_exists("training_load_snapshots"):
        return
    if column_exists("training_load_snapshots", "workout_signature"):
        op.drop_column("training_load_snapshots", "workout_signature")
