"""add deload_enabled to training_plans

Part of the "cut 30% every 4th week" deload feature — see
backend/services/load_plan.py's DELOAD_CUT_FRACTION / compute_load_plan's
deload_enabled param, and docs/calculations/load-plan.md. Off by default
(existing plans keep today's behaviour until an athlete opts in via the
Plan-tab settings panel checkbox).

Revision ID: f56d6c6ddbbb
Revises: 5048c8389b3b
Create Date: 2026-07-09 21:07:28.131878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'f56d6c6ddbbb'
down_revision: Union[str, Sequence[str], None] = '5048c8389b3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists("training_plans", "deload_enabled"):
        op.add_column(
            "training_plans",
            sa.Column("deload_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if column_exists("training_plans", "deload_enabled"):
        op.drop_column("training_plans", "deload_enabled")
