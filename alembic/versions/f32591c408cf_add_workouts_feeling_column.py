"""add workouts.feeling column

Self-reported effort feeling (issue #1241): a single nullable column tagged from
either the Plan tab (the matched workout) or the Log tab, constrained to
'hard' | 'ok' | 'easy'. Does not affect scores.

Idempotent: guarded by column_exists so it is a no-op where the column (or its
CHECK constraint) already exists.

Revision ID: f32591c408cf
Revises: 660dc2f1b517
Create Date: 2026-07-03 00:35:28.754899

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'f32591c408cf'
down_revision: Union[str, Sequence[str], None] = '660dc2f1b517'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "feeling"):
        op.add_column(
            "workouts",
            sa.Column("feeling", sa.String(length=10), nullable=True),
        )
        op.create_check_constraint(
            "ck_workouts_feeling_values",
            "workouts",
            "feeling IS NULL OR feeling IN ('hard', 'ok', 'easy')",
        )


def downgrade() -> None:
    if column_exists("workouts", "feeling"):
        op.drop_constraint("ck_workouts_feeling_values", "workouts", type_="check")
        op.drop_column("workouts", "feeling")
