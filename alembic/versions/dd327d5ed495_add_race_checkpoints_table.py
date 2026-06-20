"""Add race_checkpoints table for structured race milestones.

Revision ID: dd327d5ed495
Revises: 382389e81d09
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "dd327d5ed495"
down_revision: Union[str, None] = "5879c4f0c2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("race_checkpoints"):
        return

    op.create_table(
        "race_checkpoints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("race_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("target_distance_km", sa.Numeric(8, 3), nullable=True),
        sa.Column("target_pace_seconds_per_km", sa.Integer(), nullable=True),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "met",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "met_override",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("met_workout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.id"],
            ondelete="CASCADE",
            name="race_checkpoints_race_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="race_checkpoints_user_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["met_workout_id"],
            ["workouts.id"],
            ondelete="SET NULL",
            name="race_checkpoints_met_workout_id_fkey",
        ),
    )
    op.create_index("ix_race_checkpoints_race_id", "race_checkpoints", ["race_id"])
    op.create_index("ix_race_checkpoints_user_id", "race_checkpoints", ["user_id"])


def downgrade() -> None:
    if not table_exists("race_checkpoints"):
        return

    op.drop_index("ix_race_checkpoints_user_id", table_name="race_checkpoints")
    op.drop_index("ix_race_checkpoints_race_id", table_name="race_checkpoints")
    op.drop_table("race_checkpoints")
