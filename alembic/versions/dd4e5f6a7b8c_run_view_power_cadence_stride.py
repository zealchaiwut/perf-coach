"""Add power/cadence/stride metrics for the run-workout view.

workouts: avg_power, max_power, np (normalized power), avg_cadence_spm,
          avg_stride_m  — workout-level Stryd aggregates.
workout_splits: avg_power, cadence_spm, stride_length_m — per-km Stryd metrics.

All nullable (manual runs / no Stryd source render "—"). Idempotent.

Revision ID: dd4e5f6a7b8c
Revises: cc3d4e5f6a7b
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "dd4e5f6a7b8c"
down_revision: Union[str, None] = "cc3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WORKOUT_COLS = {
    "avg_power": sa.Integer,
    "max_power": sa.Integer,
    "np": sa.Integer,
    "avg_cadence_spm": sa.Integer,
}
_SPLIT_COLS = {
    "avg_power": sa.Integer,
    "cadence_spm": sa.Integer,
}


def upgrade() -> None:
    for name, typ in _WORKOUT_COLS.items():
        if not column_exists("workouts", name):
            op.add_column("workouts", sa.Column(name, typ, nullable=True))
    if not column_exists("workouts", "avg_stride_m"):
        op.add_column("workouts", sa.Column("avg_stride_m", sa.Numeric(4, 2), nullable=True))
    for name, typ in _SPLIT_COLS.items():
        if not column_exists("workout_splits", name):
            op.add_column("workout_splits", sa.Column(name, typ, nullable=True))
    if not column_exists("workout_splits", "stride_length_m"):
        op.add_column("workout_splits", sa.Column("stride_length_m", sa.Numeric(4, 2), nullable=True))


def downgrade() -> None:
    for name in list(_WORKOUT_COLS) + ["avg_stride_m"]:
        if column_exists("workouts", name):
            op.drop_column("workouts", name)
    for name in list(_SPLIT_COLS) + ["stride_length_m"]:
        if column_exists("workout_splits", name):
            op.drop_column("workout_splits", name)
