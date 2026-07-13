"""add block to workout_exercises

Training-block grouping (Warm-up / Heavy compound / Superset 1 / ...) on
logged exercises — same vocabulary as PlannedSession.structure's
exercises[].block, so a logged session keeps the grouping its plan had.
Nullable: old rows and ungrouped logs render flat.

Revision ID: 1d5caaeaaa26
Revises: 51b3f3a4387c
Create Date: 2026-07-13 15:31:41.603481

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '1d5caaeaaa26'
down_revision: Union[str, Sequence[str], None] = '51b3f3a4387c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists("workout_exercises", "block"):
        op.add_column(
            "workout_exercises",
            sa.Column("block", sa.String(length=80), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if column_exists("workout_exercises", "block"):
        op.drop_column("workout_exercises", "block")
