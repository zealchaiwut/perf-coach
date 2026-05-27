"""create workout_exercises table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-27 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workout_exercises",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workout_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "display_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=True),
        sa.Column("reps", sa.String(50), nullable=True),
        sa.Column("weight", sa.String(50), nullable=True),
        sa.Column("duration", sa.String(50), nullable=True),
        sa.Column("rpe", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "sets IS NULL OR sets > 0",
            name="ck_workout_exercises_sets_positive",
        ),
        sa.CheckConstraint(
            "rpe IS NULL OR (rpe >= 1 AND rpe <= 10)",
            name="ck_workout_exercises_rpe_range",
        ),
    )
    op.create_index(
        "ix_workout_exercises_workout_id_display_order",
        "workout_exercises",
        ["workout_id", "display_order"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workout_exercises_workout_id_display_order",
        table_name="workout_exercises",
    )
    op.drop_table("workout_exercises")
