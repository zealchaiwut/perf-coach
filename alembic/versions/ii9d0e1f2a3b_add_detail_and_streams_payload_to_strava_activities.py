"""Add detail_payload and streams_payload columns to strava_activities.

Stores the full detail blob (/activities/{id}) and the per-point streams
response (/activities/{id}/streams) for each synced Strava activity. These
are used during reconciliation to populate activity_streams with second-aligned
JSONB arrays. Idempotent.

Revision ID: ii9d0e1f2a3b
Revises: hh8c9d0e1f2g
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists

revision: str = "ii9d0e1f2a3b"
down_revision: Union[str, None] = "hh8c9d0e1f2g"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("strava_activities", "detail_payload"):
        op.add_column(
            "strava_activities",
            sa.Column("detail_payload", postgresql.JSONB(), nullable=True),
        )
    if not column_exists("strava_activities", "streams_payload"):
        op.add_column(
            "strava_activities",
            sa.Column("streams_payload", postgresql.JSONB(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("strava_activities", "detail_payload"):
        op.drop_column("strava_activities", "detail_payload")
    if column_exists("strava_activities", "streams_payload"):
        op.drop_column("strava_activities", "streams_payload")
