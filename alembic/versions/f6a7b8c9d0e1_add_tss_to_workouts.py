"""add tss and tss_source columns to workouts

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-27 00:00:03.000000

Training Stress Score (TSS) is the central endurance training-load metric.
tss_source tracks how the value was set ('manual' or 'calculated') so a future
auto-calc can selectively overwrite only auto-calculated rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "38a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workouts", sa.Column("tss", sa.Float(), nullable=True))
    op.add_column("workouts", sa.Column("tss_source", sa.String(20), nullable=True))

    op.execute("""
        ALTER TABLE workouts
        ADD CONSTRAINT ck_workouts_tss_non_negative
        CHECK (tss IS NULL OR tss >= 0)
    """)
    op.execute("""
        ALTER TABLE workouts
        ADD CONSTRAINT ck_workouts_tss_source_values
        CHECK (tss_source IS NULL OR tss_source IN ('manual', 'calculated'))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_tss_source_values")
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_tss_non_negative")
    op.drop_column("workouts", "tss_source")
    op.drop_column("workouts", "tss")
