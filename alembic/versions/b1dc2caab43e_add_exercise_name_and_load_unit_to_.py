"""add_exercise_name_and_load_unit_to_session_tables

Revision ID: b1dc2caab43e
Revises: 6a4bc101eef3
Create Date: 2026-06-30 16:46:26.919851

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = 'b1dc2caab43e'
down_revision: Union[str, Sequence[str], None] = '6a4bc101eef3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add exercise_name to both session tables; add load_unit to strength_sessions."""
    if table_exists("strength_sessions"):
        if not column_exists("strength_sessions", "exercise_name"):
            op.add_column(
                "strength_sessions",
                sa.Column("exercise_name", sa.String(200), nullable=True),
            )
        if not column_exists("strength_sessions", "load_unit"):
            op.add_column(
                "strength_sessions",
                sa.Column("load_unit", sa.String(10), nullable=True),
            )
            op.create_check_constraint(
                "ck_strength_sessions_load_unit_values",
                "strength_sessions",
                "load_unit IS NULL OR load_unit IN ('kg', 'lbs')",
            )

    if table_exists("plyo_sessions"):
        if not column_exists("plyo_sessions", "exercise_name"):
            op.add_column(
                "plyo_sessions",
                sa.Column("exercise_name", sa.String(200), nullable=True),
            )


def downgrade() -> None:
    """Remove exercise_name and load_unit columns added in upgrade."""
    if table_exists("strength_sessions"):
        if column_exists("strength_sessions", "load_unit"):
            op.drop_constraint(
                "ck_strength_sessions_load_unit_values",
                "strength_sessions",
                type_="check",
            )
            op.drop_column("strength_sessions", "load_unit")
        if column_exists("strength_sessions", "exercise_name"):
            op.drop_column("strength_sessions", "exercise_name")

    if table_exists("plyo_sessions"):
        if column_exists("plyo_sessions", "exercise_name"):
            op.drop_column("plyo_sessions", "exercise_name")
