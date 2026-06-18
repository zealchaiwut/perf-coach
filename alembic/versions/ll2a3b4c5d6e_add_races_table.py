"""Add races table for tracking user target races with goal pace derivation.

Revision ID: ll2a3b4c5d6e
Revises: kk1f2a3b4c5d
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "ll2a3b4c5d6e"
down_revision: Union[str, None] = "kk1f2a3b4c5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("races"):
        return

    op.create_table(
        "races",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("race_date", sa.Date(), nullable=False),
        sa.Column("distance_km", sa.Numeric(8, 3), nullable=False),
        sa.Column("goal_time_seconds", sa.Integer(), nullable=True),
        sa.Column("goal_pace_seconds_per_km", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
            name="races_user_id_fkey",
        ),
        sa.CheckConstraint("priority IN ('A', 'B', 'C')", name="ck_races_priority_values"),
        sa.CheckConstraint(
            "status IN ('planned', 'done', 'abandoned')", name="ck_races_status_values"
        ),
        sa.CheckConstraint("distance_km > 0", name="ck_races_distance_positive"),
        sa.CheckConstraint(
            "goal_time_seconds IS NULL OR goal_time_seconds > 0",
            name="ck_races_goal_time_positive",
        ),
    )
    op.create_index("ix_races_user_id", "races", ["user_id"])


def downgrade() -> None:
    if not table_exists("races"):
        return

    op.drop_index("ix_races_user_id", table_name="races")
    op.drop_table("races")
