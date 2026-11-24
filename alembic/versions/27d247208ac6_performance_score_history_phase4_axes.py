"""performance_score_history phase4 axes

Revision ID: 27d247208ac6
Revises: 82c3e47e90f7
Create Date: 2026-11-21 22:51:43.897777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '27d247208ac6'
down_revision: Union[str, Sequence[str], None] = '82c3e47e90f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_AXIS_COLUMNS = ("durability", "economy", "strength", "mobility", "power_to_weight")


def upgrade() -> None:
    """Extend the shared daily snapshot table with the five Phase 4 axes (nullable)."""
    if not table_exists("performance_score_history"):
        return
    for col in _NEW_AXIS_COLUMNS:
        if not column_exists("performance_score_history", col):
            op.add_column("performance_score_history", sa.Column(col, sa.Float(), nullable=True))


def downgrade() -> None:
    if not table_exists("performance_score_history"):
        return
    for col in reversed(_NEW_AXIS_COLUMNS):
        if column_exists("performance_score_history", col):
            op.drop_column("performance_score_history", col)
