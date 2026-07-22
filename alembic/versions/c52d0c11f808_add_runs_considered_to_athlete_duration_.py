"""add_runs_considered_to_athlete_duration_curves

Revision ID: c52d0c11f808
Revises: f503b8e5fb1d
Create Date: 2026-07-22 12:19:55.349054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

# revision identifiers, used by Alembic.
revision: str = 'c52d0c11f808'
down_revision: Union[str, Sequence[str], None] = 'f503b8e5fb1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add athlete_duration_curves.runs_considered (nullable int).

    Stamps how many run workouts the last curve rebuild considered, so the
    run-personal-records endpoint can skip re-enqueueing a rebuild for an
    athlete whose runs legitimately produce an empty curve until a new run
    appears.
    """
    if table_exists("athlete_duration_curves") and not column_exists(
        "athlete_duration_curves", "runs_considered"
    ):
        op.add_column(
            "athlete_duration_curves",
            sa.Column("runs_considered", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    """Drop athlete_duration_curves.runs_considered."""
    if table_exists("athlete_duration_curves") and column_exists(
        "athlete_duration_curves", "runs_considered"
    ):
        op.drop_column("athlete_duration_curves", "runs_considered")
