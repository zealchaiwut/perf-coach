"""add_grade_percent_stryd_flat_equivalent_pace_workout

Adds grade_percent (treadmill incline) to stryd_activities and
flat_equivalent_pace (NGP result) to workouts (issue #1219).

Revision ID: 4753105d42ae
Revises: 4ad3bf3fff49
Create Date: 2026-07-05 01:57:17.855683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '4753105d42ae'
down_revision: Union[str, Sequence[str], None] = '4ad3bf3fff49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("stryd_activities", "grade_percent"):
        op.add_column(
            "stryd_activities",
            sa.Column("grade_percent", sa.Float(), nullable=True),
        )

    if not column_exists("workouts", "flat_equivalent_pace"):
        op.add_column(
            "workouts",
            sa.Column("flat_equivalent_pace", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("workouts", "flat_equivalent_pace"):
        op.drop_column("workouts", "flat_equivalent_pace")

    if column_exists("stryd_activities", "grade_percent"):
        op.drop_column("stryd_activities", "grade_percent")
