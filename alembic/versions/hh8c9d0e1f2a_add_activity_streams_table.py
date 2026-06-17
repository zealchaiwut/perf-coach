"""Add activity_streams table for per-sample time-series channel data.

Stores compact JSON arrays of power, heart rate, pace, cadence, GPS, and
altitude samples ingested from Strava or Stryd. One row per workout; the
absence of a row is the canonical signal that a workout has no stream data.

Revision ID: hh8c9d0e1f2a
Revises: gg7b8c9d0e1f
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "hh8c9d0e1f2a"
down_revision: Union[str, None] = "gg7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("activity_streams"):
        return

    op.create_table(
        "activity_streams",
        sa.Column(
            "workout_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("sample_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("time_offset_seconds", postgresql.JSONB(), nullable=True),
        sa.Column("power_w", postgresql.JSONB(), nullable=True),
        sa.Column("heart_rate_bpm", postgresql.JSONB(), nullable=True),
        sa.Column("pace_seconds_per_km", postgresql.JSONB(), nullable=True),
        sa.Column("cadence_spm", postgresql.JSONB(), nullable=True),
        sa.Column("altitude_m", postgresql.JSONB(), nullable=True),
        sa.Column("latitude", postgresql.JSONB(), nullable=True),
        sa.Column("longitude", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "source IS NULL OR source IN ('strava', 'stryd')",
            name="ck_activity_streams_source_values",
        ),
    )


def downgrade() -> None:
    if not table_exists("activity_streams"):
        return
    op.drop_table("activity_streams")
