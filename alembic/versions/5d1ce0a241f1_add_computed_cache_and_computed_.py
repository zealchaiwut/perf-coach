"""add computed_cache and computed_signature to training_plans

Revision ID: 5d1ce0a241f1
Revises: d8859166acd7
Create Date: 2026-07-02 10:02:19.267059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '5d1ce0a241f1'
down_revision: Union[str, Sequence[str], None] = 'd8859166acd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add plan-level computed-bundle cache columns (idempotent)."""
    if not column_exists("training_plans", "computed_cache"):
        op.add_column(
            "training_plans",
            sa.Column("computed_cache", postgresql.JSONB(), nullable=True),
        )
    if not column_exists("training_plans", "computed_signature"):
        op.add_column(
            "training_plans",
            sa.Column("computed_signature", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    """Drop the computed-bundle cache columns (idempotent)."""
    if column_exists("training_plans", "computed_signature"):
        op.drop_column("training_plans", "computed_signature")
    if column_exists("training_plans", "computed_cache"):
        op.drop_column("training_plans", "computed_cache")
