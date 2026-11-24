"""add strength tss method and session effort

Revision ID: f77afafbddc4
Revises: 4cd121d81626
Create Date: 2026-11-20 15:47:09.661154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = "f77afafbddc4"
down_revision: Union[str, Sequence[str], None] = "4cd121d81626"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "strength_tss_method"):
        op.add_column("workouts", sa.Column("strength_tss_method", sa.String(20), nullable=True))
    if not column_exists("workouts", "session_effort"):
        op.add_column("workouts", sa.Column("session_effort", sa.Integer(), nullable=True))


def downgrade() -> None:
    if column_exists("workouts", "session_effort"):
        op.drop_column("workouts", "session_effort")
    if column_exists("workouts", "strength_tss_method"):
        op.drop_column("workouts", "strength_tss_method")