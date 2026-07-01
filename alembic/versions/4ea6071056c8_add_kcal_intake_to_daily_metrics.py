"""add_kcal_intake_to_daily_metrics

Revision ID: 4ea6071056c8
Revises: 02ea347c3bd1
Create Date: 2026-06-30 23:41:37.605704

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = '4ea6071056c8'
down_revision: Union[str, Sequence[str], None] = '02ea347c3bd1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("daily_metrics", "kcal_intake"):
        op.add_column(
            "daily_metrics",
            sa.Column("kcal_intake", sa.Integer(), nullable=True),
        )
        op.create_check_constraint(
            "ck_daily_metrics_kcal_intake",
            "daily_metrics",
            "kcal_intake IS NULL OR kcal_intake > 0",
        )


def downgrade() -> None:
    if column_exists("daily_metrics", "kcal_intake"):
        op.drop_constraint("ck_daily_metrics_kcal_intake", "daily_metrics", type_="check")
        op.drop_column("daily_metrics", "kcal_intake")
