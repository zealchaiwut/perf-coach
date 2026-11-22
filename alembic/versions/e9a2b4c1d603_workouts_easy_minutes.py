"""workouts easy_minutes for durability Z1+Z2

Revision ID: e9a2b4c1d603
Revises: d8f1c2a39e04
Create Date: 2026-11-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "e9a2b4c1d603"
down_revision: Union[str, Sequence[str], None] = "d8f1c2a39e04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("workouts") and not column_exists("workouts", "easy_minutes"):
        op.add_column("workouts", sa.Column("easy_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    if table_exists("workouts") and column_exists("workouts", "easy_minutes"):
        op.drop_column("workouts", "easy_minutes")