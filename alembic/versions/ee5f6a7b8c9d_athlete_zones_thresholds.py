"""Add max_hr + Zone-2 band + weekly Zone-2 target to user_preferences.

Extends the existing thresholds (ftp_w / threshold_hr / threshold_pace) used by
tss.py with the fields TSS-fallback (⑤) and zone2_minutes compute (⑥) need.
All nullable — defaults are applied at the API layer (_PREFS_DEFAULTS). Idempotent.

Revision ID: ee5f6a7b8c9d
Revises: dd4e5f6a7b8c
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "ee5f6a7b8c9d"
down_revision: Union[str, None] = "dd4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = ["max_hr", "zone2_hr_min", "zone2_hr_max", "weekly_zone2_target_min"]


def upgrade() -> None:
    for name in _COLS:
        if not column_exists("user_preferences", name):
            op.add_column("user_preferences", sa.Column(name, sa.Integer, nullable=True))


def downgrade() -> None:
    for name in _COLS:
        if column_exists("user_preferences", name):
            op.drop_column("user_preferences", name)
