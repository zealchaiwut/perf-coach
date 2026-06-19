"""Add race_type column to races table for race vs checkpoint distinction.

Revision ID: mm3c4d5e6f7g
Revises: ll2a3b4c5d6e
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "mm3c4d5e6f7g"
down_revision: Union[str, None] = "ll2a3b4c5d6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("races"):
        return
    if column_exists("races", "race_type"):
        return

    op.add_column(
        "races",
        sa.Column(
            "race_type",
            sa.String(20),
            nullable=False,
            server_default="race",
        ),
    )
    op.create_check_constraint(
        "ck_races_race_type_values",
        "races",
        "race_type IN ('race', 'checkpoint')",
    )


def downgrade() -> None:
    if not table_exists("races"):
        return
    if not column_exists("races", "race_type"):
        return

    op.drop_constraint("ck_races_race_type_values", "races", type_="check")
    op.drop_column("races", "race_type")
