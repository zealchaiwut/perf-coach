"""Add lap_type column to workout_splits.

Enables the Run View / Run Builder to distinguish auto (1-km) splits from
manually-entered lap rows. Default 'auto' so existing rows are unaffected.
Nullable text; only 'auto' and 'manual' are written by the app. Idempotent.

Revision ID: gg7b8c9d0e1f
Revises: ff6a7b8c9d0e
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "gg7b8c9d0e1f"
down_revision: Union[str, None] = "ff6a7b8c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workout_splits", "lap_type"):
        op.add_column(
            "workout_splits",
            sa.Column(
                "lap_type",
                sa.String(10),
                nullable=True,
                server_default=sa.text("'auto'"),
            ),
        )


def downgrade() -> None:
    if column_exists("workout_splits", "lap_type"):
        op.drop_column("workout_splits", "lap_type")
