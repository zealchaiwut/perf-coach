"""Add channel_attribution column to activity_streams and allow 'merged' source.

Stores the per-channel source-attribution map produced by select_channels when
a workout has data from two recording devices (e.g. a Garmin watch and a Stryd
foot pod). The value is a JSONB object such as:

    {"power_w": "stryd", "latitude": "garmin", "heart_rate_bpm": "stryd"}

The source check constraint is updated to also allow the value 'merged', which
is written by apply_channel_selection after channel selection completes.

Revision ID: ii9d0e1f2g3h
Revises: hh8c9d0e1f2g
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists

revision: str = "ii9d0e1f2g3h"
down_revision: Union[str, None] = "hh8c9d0e1f2g"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add channel_attribution column (idempotent)
    if not column_exists("activity_streams", "channel_attribution"):
        op.add_column(
            "activity_streams",
            sa.Column("channel_attribution", postgresql.JSONB(), nullable=True),
        )

    # Update source check constraint to allow 'merged'
    # Postgres requires drop + recreate to change a check constraint.
    op.execute(
        "ALTER TABLE activity_streams "
        "DROP CONSTRAINT IF EXISTS ck_activity_streams_source_values"
    )
    op.execute(
        "ALTER TABLE activity_streams "
        "ADD CONSTRAINT ck_activity_streams_source_values "
        "CHECK (source IS NULL OR source IN ('strava', 'stryd', 'merged'))"
    )


def downgrade() -> None:
    # Remove merged rows before restoring the tighter constraint
    op.execute(
        "DELETE FROM activity_streams WHERE source = 'merged'"
    )

    op.execute(
        "ALTER TABLE activity_streams "
        "DROP CONSTRAINT IF EXISTS ck_activity_streams_source_values"
    )
    op.execute(
        "ALTER TABLE activity_streams "
        "ADD CONSTRAINT ck_activity_streams_source_values "
        "CHECK (source IS NULL OR source IN ('strava', 'stryd'))"
    )

    if column_exists("activity_streams", "channel_attribution"):
        op.drop_column("activity_streams", "channel_attribution")
