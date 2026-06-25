"""Add streams_payload column to stryd_activities.

Stores the raw per-point streams response (timestamp_list, heart_rate_list,
total_power_list, cadence_list, speed_list, etc.) before the *_list keys are
stripped by _slim_payload. The reconcile phase reads this column to populate
activity_streams with second-aligned JSONB arrays. Idempotent.

Revision ID: hh8c9d0e1f2g
Revises: hh8c9d0e1f2a
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists

revision: str = "hh8c9d0e1f2g"
down_revision: Union[str, None] = "hh8c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("stryd_activities", "streams_payload"):
        op.add_column(
            "stryd_activities",
            sa.Column("streams_payload", postgresql.JSONB(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("stryd_activities", "streams_payload"):
        op.drop_column("stryd_activities", "streams_payload")
