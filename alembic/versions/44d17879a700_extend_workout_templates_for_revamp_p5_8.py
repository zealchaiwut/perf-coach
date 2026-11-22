"""extend_workout_templates_for_revamp_p5_8

Revision ID: 44d17879a700
Revises: a88b6df7cbcf
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "44d17879a700"
down_revision: Union[str, Sequence[str], None] = "a88b6df7cbcf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("workout_templates"):
        return
    if not column_exists("workout_templates", "session_type"):
        op.add_column(
            "workout_templates",
            sa.Column("session_type", sa.String(20), server_default="strength", nullable=False),
        )
    if not column_exists("workout_templates", "tss_estimate"):
        op.add_column("workout_templates", sa.Column("tss_estimate", sa.Float(), nullable=True))
    if not column_exists("workout_templates", "last_used_at"):
        op.add_column(
            "workout_templates",
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if not table_exists("workout_templates"):
        return
    if column_exists("workout_templates", "last_used_at"):
        op.drop_column("workout_templates", "last_used_at")
    if column_exists("workout_templates", "tss_estimate"):
        op.drop_column("workout_templates", "tss_estimate")
    if column_exists("workout_templates", "session_type"):
        op.drop_column("workout_templates", "session_type")