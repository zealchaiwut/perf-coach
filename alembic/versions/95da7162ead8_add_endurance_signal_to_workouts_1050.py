"""Add endurance signal fields to workouts (issue #1050).

Five new nullable columns store the per-run aerobic durability metric:
  endurance_signal        - Float   100 - decoupling_percent, floored at 0; null for short runs
  decoupling_percent      - Float   ((e1 - e2) / e1) * 100; positive = fade
  efficiency_first_half   - Float   power/HR or speed/HR for first half of run
  efficiency_second_half  - Float   same metric for second half
  endurance_signal_source - String  "power_hr" | "speed_hr" | null

All columns are idempotent via column_exists checks and default to null.
Mirrors the schema from issue #1049 if that migration has not yet been applied.

Revision ID: 95da7162ead8
Revises: 5e52880eedd3
Create Date: 2026-06-27 15:21:04.337038
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = '95da7162ead8'
down_revision: Union[str, Sequence[str], None] = '5e52880eedd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "endurance_signal"):
        op.add_column("workouts", sa.Column("endurance_signal", sa.Float(), nullable=True))
    if not column_exists("workouts", "decoupling_percent"):
        op.add_column("workouts", sa.Column("decoupling_percent", sa.Float(), nullable=True))
    if not column_exists("workouts", "efficiency_first_half"):
        op.add_column("workouts", sa.Column("efficiency_first_half", sa.Float(), nullable=True))
    if not column_exists("workouts", "efficiency_second_half"):
        op.add_column("workouts", sa.Column("efficiency_second_half", sa.Float(), nullable=True))
    if not column_exists("workouts", "endurance_signal_source"):
        op.add_column("workouts", sa.Column("endurance_signal_source", sa.String(20), nullable=True))


def downgrade() -> None:
    for col in (
        "endurance_signal_source",
        "efficiency_second_half",
        "efficiency_first_half",
        "decoupling_percent",
        "endurance_signal",
    ):
        if column_exists("workouts", col):
            op.drop_column("workouts", col)
