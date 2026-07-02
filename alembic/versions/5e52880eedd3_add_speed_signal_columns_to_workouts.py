"""Add speed_signal columns to workouts table (issue #1048).

Four nullable columns store the computed per-run speed signal:
  speed_signal               - Float   best short-effort ratio vs threshold, or null
  speed_signal_basis         - String  "power" | "pace" | "heart_rate" | null
  speed_signal_window_seconds - Integer duration of the best window used, or null
  speed_signal_source        - Text    descriptive computation path string, or null

All columns default to null; existing rows are unaffected.

Revision ID: 5e52880eedd3
Revises: 15f71886259c
Create Date: 2026-06-27 15:00:34.193077
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = '5e52880eedd3'
down_revision: Union[str, Sequence[str], None] = '15f71886259c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "speed_signal"):
        op.add_column("workouts", sa.Column("speed_signal", sa.Float(), nullable=True))
    if not column_exists("workouts", "speed_signal_basis"):
        op.add_column("workouts", sa.Column("speed_signal_basis", sa.String(20), nullable=True))
    if not column_exists("workouts", "speed_signal_window_seconds"):
        op.add_column("workouts", sa.Column("speed_signal_window_seconds", sa.Integer(), nullable=True))
    if not column_exists("workouts", "speed_signal_source"):
        op.add_column("workouts", sa.Column("speed_signal_source", sa.Text(), nullable=True))


def downgrade() -> None:
    if column_exists("workouts", "speed_signal_source"):
        op.drop_column("workouts", "speed_signal_source")
    if column_exists("workouts", "speed_signal_window_seconds"):
        op.drop_column("workouts", "speed_signal_window_seconds")
    if column_exists("workouts", "speed_signal_basis"):
        op.drop_column("workouts", "speed_signal_basis")
    if column_exists("workouts", "speed_signal"):
        op.drop_column("workouts", "speed_signal")
