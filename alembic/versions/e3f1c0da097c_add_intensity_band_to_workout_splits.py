"""Add intensity_band column to workout_splits.

Stores the per-lap intensity band (easy/steady/tempo/threshold/hard) computed
from fraction-of-threshold comparisons. Band is classified from power, then
pace, then HR in priority order using thresholds from user_preferences.

Revision ID: e3f1c0da097c
Revises: 3f9e1b2c4a7d
Create Date: 2026-06-30 12:33:12.039226

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = 'e3f1c0da097c'
down_revision: Union[str, Sequence[str], None] = '3f9e1b2c4a7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workout_splits", "intensity_band"):
        op.add_column(
            "workout_splits",
            sa.Column("intensity_band", sa.String(20), nullable=True),
        )
        op.create_check_constraint(
            "ck_workout_splits_intensity_band_values",
            "workout_splits",
            "intensity_band IS NULL OR intensity_band IN ('easy', 'steady', 'tempo', 'threshold', 'hard')",
        )


def downgrade() -> None:
    if column_exists("workout_splits", "intensity_band"):
        op.drop_constraint(
            "ck_workout_splits_intensity_band_values",
            "workout_splits",
            type_="check",
        )
        op.drop_column("workout_splits", "intensity_band")
