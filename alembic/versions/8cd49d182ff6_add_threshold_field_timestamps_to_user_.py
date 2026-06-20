"""add_threshold_field_timestamps_to_user_preferences

Revision ID: 8cd49d182ff6
Revises: 990a3039d023
Create Date: 2026-06-20 12:03:48.948142

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '8cd49d182ff6'
down_revision: Union[str, Sequence[str], None] = '990a3039d023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "user_preferences"
_COLS = [
    "ftp_w_updated_at",
    "threshold_hr_updated_at",
    "threshold_pace_seconds_per_km_updated_at",
    "zone2_hr_min_updated_at",
    "zone2_hr_max_updated_at",
]


def upgrade() -> None:
    for col in _COLS:
        if not column_exists(_TABLE, col):
            op.add_column(
                _TABLE,
                sa.Column(col, sa.DateTime(timezone=True), nullable=True),
            )


def downgrade() -> None:
    for col in reversed(_COLS):
        if column_exists(_TABLE, col):
            op.drop_column(_TABLE, col)
