"""long_run_ladder_a_race_settings_p6_8

Revision ID: 02d0f3df6d96
Revises: 2f84f8c79884
Create Date: 2026-11-22 15:52:53.649292

Revamp P6-8 (#1882): A-race long-run need and manual weekly target.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "02d0f3df6d96"
down_revision: Union[str, Sequence[str], None] = "2f84f8c79884"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("races", "long_run_need_seconds"):
        op.add_column("races", sa.Column("long_run_need_seconds", sa.Integer(), nullable=True))
    if not column_exists("races", "long_run_manual_target_seconds"):
        op.add_column("races", sa.Column("long_run_manual_target_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    if column_exists("races", "long_run_manual_target_seconds"):
        op.drop_column("races", "long_run_manual_target_seconds")
    if column_exists("races", "long_run_need_seconds"):
        op.drop_column("races", "long_run_need_seconds")
