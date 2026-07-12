"""Add auto_periodize boolean to fuel_settings (issue #1357).

When True (the default), the weekly training phase (race/taper/ramp/base)
modulates the effective calorie deficit. When False, the configured
deficit_kcal is always applied unchanged.

Revision ID: 3e7f9a2c1d05
Revises: bf3b956dd2e0
Create Date: 2026-07-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "3e7f9a2c1d05"
down_revision: Union[str, None] = "bf3b956dd2e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("fuel_settings", "auto_periodize"):
        op.add_column(
            "fuel_settings",
            sa.Column(
                "auto_periodize",
                sa.Boolean(),
                nullable=True,
            ),
        )
        op.execute("UPDATE fuel_settings SET auto_periodize = TRUE")
        op.alter_column(
            "fuel_settings",
            "auto_periodize",
            nullable=False,
            server_default=sa.text("true"),
        )


def downgrade() -> None:
    if column_exists("fuel_settings", "auto_periodize"):
        op.drop_column("fuel_settings", "auto_periodize")
