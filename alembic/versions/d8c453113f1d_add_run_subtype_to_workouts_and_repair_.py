"""add run_subtype to workouts and repair interval-typed rows

Revision ID: d8c453113f1d
Revises: c348d3b407f6
Create Date: 2026-07-02 14:55:01.394849

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'd8c453113f1d'
down_revision: Union[str, Sequence[str], None] = 'c348d3b407f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add workouts.run_subtype and repair rows mistakenly typed 'interval'.

    Idempotent: the column add is guarded, and the repair UPDATE only matches
    rows still typed 'interval' (a run subtype must live in run_subtype, with
    workout_type staying 'run' so the row keeps the full run pipeline).
    """
    if not column_exists("workouts", "run_subtype"):
        op.add_column(
            "workouts",
            sa.Column("run_subtype", sa.String(length=20), nullable=True),
        )
    # Repair the two rows the user already marked (workout_type='interval'):
    # restore them to run + run_subtype='interval'.
    op.execute(
        "UPDATE workouts SET workout_type = 'run', run_subtype = 'interval' "
        "WHERE workout_type = 'interval'"
    )


def downgrade() -> None:
    """Drop workouts.run_subtype (idempotent). The repair is not reversed."""
    if column_exists("workouts", "run_subtype"):
        op.drop_column("workouts", "run_subtype")
