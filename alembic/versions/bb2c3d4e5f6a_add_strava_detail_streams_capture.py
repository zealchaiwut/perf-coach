"""Add full-capture columns to strava_activities.

Captures everything Strava exposes per activity:
- detail_payload: full /activities/{id} response (laps, splits_metric,
  best_efforts, segment_efforts, full map polyline, calories, gear, …)
- streams_payload: full /activities/{id}/streams response (per-point time,
  latlng GPS, altitude, velocity_smooth, heartrate, cadence, watts, …)
- avg_cadence / suffer_score: promoted summary fields worth querying directly.

All nullable + idempotent so it is safe on any existing DB.

Revision ID: bb2c3d4e5f6a
Revises: aa1b2c3d4e5f
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from helpers import column_exists

revision: str = "bb2c3d4e5f6a"
down_revision: Union[str, None] = "aa1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("strava_activities", "detail_payload"):
        op.add_column("strava_activities", sa.Column("detail_payload", JSONB, nullable=True))
    if not column_exists("strava_activities", "streams_payload"):
        op.add_column("strava_activities", sa.Column("streams_payload", JSONB, nullable=True))
    if not column_exists("strava_activities", "avg_cadence"):
        op.add_column("strava_activities", sa.Column("avg_cadence", sa.Numeric(6, 2), nullable=True))
    if not column_exists("strava_activities", "suffer_score"):
        op.add_column("strava_activities", sa.Column("suffer_score", sa.Integer, nullable=True))


def downgrade() -> None:
    for col in ("detail_payload", "streams_payload", "avg_cadence", "suffer_score"):
        if column_exists("strava_activities", col):
            op.drop_column("strava_activities", col)
