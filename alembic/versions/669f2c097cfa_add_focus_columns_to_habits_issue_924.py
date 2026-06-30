"""add_focus_columns_to_habits_issue_924

Adds nullable is_focus (boolean) and focus_since (timestamptz) columns to the
habits table. Guarded by column_exists checks so running twice produces no error.

Revision ID: 669f2c097cfa
Revises: 0d100c1f1867
Create Date: 2026-06-25 20:33:58.604603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists

revision: str = "669f2c097cfa"
down_revision: Union[str, Sequence[str], None] = "0d100c1f1867"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("habits", "is_focus"):
        op.add_column(
            "habits",
            sa.Column("is_focus", sa.Boolean(), nullable=True),
        )
    if not column_exists("habits", "focus_since"):
        op.add_column(
            "habits",
            sa.Column("focus_since", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if column_exists("habits", "focus_since"):
        op.drop_column("habits", "focus_since")
    if column_exists("habits", "is_focus"):
        op.drop_column("habits", "is_focus")
