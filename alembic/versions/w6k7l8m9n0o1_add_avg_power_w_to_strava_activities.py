"""Idempotently add avg_power_w to strava_activities.

The column is included in the original create_table migration. This migration
adds it only if absent, covering databases created before that column was added.

Revision ID: w6k7l8m9n0o1
Revises: v5j6k7l8m9n0
Create Date: 2026-06-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "w6k7l8m9n0o1"
down_revision: Union[str, None] = "v5j6k7l8m9n0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("strava_activities", "avg_power_w"):
        op.add_column(
            "strava_activities",
            sa.Column("avg_power_w", sa.Integer, nullable=True),
        )


def downgrade() -> None:
    if column_exists("strava_activities", "avg_power_w"):
        op.drop_column("strava_activities", "avg_power_w")
