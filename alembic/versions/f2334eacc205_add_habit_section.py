"""add_habit_section

Adds section column (training|general, default general) to habits table.
Backfills all existing rows to 'general'.

Revision ID: f2334eacc205
Revises: 5b2f59e19e14
Create Date: 2026-07-17 15:43:57.164342

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = 'f2334eacc205'
down_revision: Union[str, Sequence[str], None] = '5b2f59e19e14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("habits", "section"):
        op.add_column(
            "habits",
            sa.Column("section", sa.Text(), nullable=True),
        )
    # Backfill all existing rows to 'general'
    op.execute("UPDATE habits SET section = 'general' WHERE section IS NULL")
    op.alter_column("habits", "section", nullable=False, server_default="general")
    # Add check constraint
    op.create_check_constraint(
        "ck_habits_section_values",
        "habits",
        "section IN ('training', 'general')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_habits_section_values", "habits", type_="check")
    op.drop_column("habits", "section")
