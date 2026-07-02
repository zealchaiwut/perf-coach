"""make_sleep_stage_cols_nullable

Allow deep_minutes, rem_minutes, light_minutes, awake_minutes to be NULL so
Health Sync CSVs that omit sleep-stage breakdowns can be imported cleanly.

Revision ID: 53b033936666
Revises: ec0e2c456452
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import table_exists, column_exists

revision: str = "53b033936666"
down_revision: Union[str, Sequence[str], None] = "ec0e2c456452"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = ["deep_minutes", "rem_minutes", "light_minutes", "awake_minutes"]


def upgrade() -> None:
    if not table_exists("sleep_records"):
        return
    for col in _COLS:
        if column_exists("sleep_records", col):
            op.alter_column("sleep_records", col, nullable=True)


def downgrade() -> None:
    if not table_exists("sleep_records"):
        return
    for col in _COLS:
        if column_exists("sleep_records", col):
            op.execute(
                sa.text(
                    f"UPDATE sleep_records SET {col} = 0 WHERE {col} IS NULL"
                )
            )
            op.alter_column("sleep_records", col, nullable=False)
