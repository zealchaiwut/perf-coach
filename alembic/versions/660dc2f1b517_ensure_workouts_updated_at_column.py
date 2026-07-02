"""ensure workouts.updated_at column exists (fix-loopholes Task 7)

backend/models.py's Workout.updated_at was mapped to a column that existed
in some environments already but was never added via an Alembic migration
(no provenance in this repo). _plan_signature and the PATCH workout
endpoint both depend on it to invalidate the cached Plan bundle when a
workout is edited. Idempotent: guarded by column_exists so it's a no-op
where the column is already present.

Revision ID: 660dc2f1b517
Revises: 6ce18fda0701
Create Date: 2026-07-02 19:51:08.415784

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '660dc2f1b517'
down_revision: Union[str, Sequence[str], None] = '6ce18fda0701'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "updated_at"):
        op.add_column(
            "workouts",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if column_exists("workouts", "updated_at"):
        op.drop_column("workouts", "updated_at")
