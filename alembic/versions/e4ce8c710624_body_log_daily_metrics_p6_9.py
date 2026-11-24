"""body_log_daily_metrics_p6_9

Revision ID: e4ce8c710624
Revises: f0b841dbec0f
Create Date: 2026-11-22 15:58:51.092526

Revamp P6-9 (#1883): lunch rule, feet, steps on daily_metrics.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "e4ce8c710624"
down_revision: Union[str, Sequence[str], None] = "f0b841dbec0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("daily_metrics", "lunch_rule"):
        op.add_column("daily_metrics", sa.Column("lunch_rule", sa.Boolean(), nullable=True))
    if not column_exists("daily_metrics", "feet"):
        op.add_column("daily_metrics", sa.Column("feet", sa.Integer(), nullable=True))
    if not column_exists("daily_metrics", "steps"):
        op.add_column("daily_metrics", sa.Column("steps", sa.Integer(), nullable=True))
    if not column_exists("daily_metrics", "steps_source"):
        op.add_column("daily_metrics", sa.Column("steps_source", sa.String(length=20), nullable=True))


def downgrade() -> None:
    if column_exists("daily_metrics", "steps_source"):
        op.drop_column("daily_metrics", "steps_source")
    if column_exists("daily_metrics", "steps"):
        op.drop_column("daily_metrics", "steps")
    if column_exists("daily_metrics", "feet"):
        op.drop_column("daily_metrics", "feet")
    if column_exists("daily_metrics", "lunch_rule"):
        op.drop_column("daily_metrics", "lunch_rule")