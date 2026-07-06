"""add_manual_laps_to_stryd_activities

Add stryd_activities.manual_laps JSONB column. Stores the output of
compute_manual_laps() at sync time so the workout detail endpoint does not
need to materialise the full streams_payload on every request (issue #1295).

Revision ID: fa2a764aa719
Revises: c7750b0bd23f
Create Date: 2026-07-06 18:50:58.261962

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists

revision: str = 'fa2a764aa719'
down_revision: Union[str, Sequence[str], None] = 'c7750b0bd23f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("stryd_activities", "manual_laps"):
        op.add_column(
            "stryd_activities",
            sa.Column("manual_laps", postgresql.JSONB, nullable=True),
        )


def downgrade() -> None:
    if column_exists("stryd_activities", "manual_laps"):
        op.drop_column("stryd_activities", "manual_laps")
