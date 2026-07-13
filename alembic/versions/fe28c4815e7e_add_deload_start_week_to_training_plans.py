"""add deload_start_week to training_plans

Which week of the 4-week cycle the deload lands on (1-4): first deload at
this week_index, then every 4 weeks after (4 -> 4, 8, 12; 2 -> 2, 6, 10).
Default 4 preserves the pre-existing "every 4th week" behaviour for every
plan that already has deload_enabled on. See backend/services/load_plan.py's
compute_load_plan(deload_start_week=...).

Revision ID: fe28c4815e7e
Revises: 8b73d5c83348
Create Date: 2026-07-12 20:24:50.190435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'fe28c4815e7e'
down_revision: Union[str, Sequence[str], None] = '8b73d5c83348'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists("training_plans", "deload_start_week"):
        op.add_column(
            "training_plans",
            sa.Column("deload_start_week", sa.Integer(), server_default=sa.text("4"), nullable=False),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if column_exists("training_plans", "deload_start_week"):
        op.drop_column("training_plans", "deload_start_week")
