"""run_form_metrics form_power_ratio

Revision ID: bf3569410f9f
Revises: 27d247208ac6
Create Date: 2026-11-21 22:53:59.560548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = 'bf3569410f9f'
down_revision: Union[str, Sequence[str], None] = '27d247208ac6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add form_power_ratio (form power / running power) for the economy axis (P4-3)."""
    if table_exists("run_form_metrics") and not column_exists("run_form_metrics", "form_power_ratio"):
        op.add_column(
            "run_form_metrics",
            sa.Column("form_power_ratio", sa.Numeric(6, 4), nullable=True),
        )


def downgrade() -> None:
    if table_exists("run_form_metrics") and column_exists("run_form_metrics", "form_power_ratio"):
        op.drop_column("run_form_metrics", "form_power_ratio")
