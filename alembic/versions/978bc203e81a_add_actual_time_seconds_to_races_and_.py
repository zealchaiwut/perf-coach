"""add_actual_time_seconds_to_races_and_calibration_constants_to_user_preferences

Revision ID: 978bc203e81a
Revises: 145b95d5baf0, d915ffcb4c0c
Create Date: 2026-06-20 10:05:55.532020

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '978bc203e81a'
down_revision: Union[str, Sequence[str], None] = ('145b95d5baf0', 'd915ffcb4c0c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("races", "actual_time_seconds"):
        op.add_column(
            "races",
            sa.Column("actual_time_seconds", sa.Integer(), nullable=True),
        )

    if not column_exists("user_preferences", "ctl_days"):
        op.add_column(
            "user_preferences",
            sa.Column("ctl_days", sa.Integer(), nullable=True),
        )

    if not column_exists("user_preferences", "atl_days"):
        op.add_column(
            "user_preferences",
            sa.Column("atl_days", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("user_preferences", "atl_days"):
        op.drop_column("user_preferences", "atl_days")

    if column_exists("user_preferences", "ctl_days"):
        op.drop_column("user_preferences", "ctl_days")

    if column_exists("races", "actual_time_seconds"):
        op.drop_column("races", "actual_time_seconds")
