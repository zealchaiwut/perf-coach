"""add_elapsed_time_columns_for_stop_detection

Revision ID: 1fbab07a5c4d
Revises: 44d17879a700
Create Date: 2026-11-22

Revamp P6-2 (#1876): store elapsed time next to moving time on workouts,
strava_activities and workout_splits. Existing duration_seconds stays = moving.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "1fbab07a5c4d"
down_revision: Union[str, Sequence[str], None] = "44d17879a700"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ("workouts", "elapsed_time_seconds"),
    ("strava_activities", "elapsed_time_seconds"),
    ("workout_splits", "moving_time_seconds"),
    ("workout_splits", "elapsed_time_seconds"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        if table_exists(table) and not column_exists(table, column):
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        if column_exists(table, column):
            op.drop_column(table, column)
