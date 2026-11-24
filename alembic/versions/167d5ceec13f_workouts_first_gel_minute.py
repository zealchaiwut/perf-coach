"""workouts_first_gel_minute

Revision ID: 167d5ceec13f
Revises: e9a2b4c1d603
Create Date: 2026-11-24 08:57:45.417737

Revamp P4-FU5 (#1897): minutes into a run when the first gel went down.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "167d5ceec13f"
down_revision: Union[str, Sequence[str], None] = "e9a2b4c1d603"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("workouts") and not column_exists("workouts", "first_gel_minute"):
        op.add_column("workouts", sa.Column("first_gel_minute", sa.Integer(), nullable=True))
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_workouts_first_gel_minute_range'
            ) THEN
                ALTER TABLE workouts ADD CONSTRAINT ck_workouts_first_gel_minute_range
                CHECK (first_gel_minute IS NULL OR (first_gel_minute >= 0 AND first_gel_minute <= 300));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_first_gel_minute_range")
    if table_exists("workouts") and column_exists("workouts", "first_gel_minute"):
        op.drop_column("workouts", "first_gel_minute")
