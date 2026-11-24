"""sprint140 session versions pending exercises

Revision ID: dff094694e51
Revises: f77afafbddc4
Create Date: 2026-11-20 16:20:30.109453

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from helpers import column_exists, table_exists

revision: str = "dff094694e51"
down_revision: Union[str, Sequence[str], None] = "f77afafbddc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("workouts", "exercises_json"):
        op.add_column("workouts", sa.Column("exercises_json", JSONB, nullable=True))
    if not column_exists("workouts", "recompute_pending"):
        op.add_column(
            "workouts",
            sa.Column("recompute_pending", sa.DateTime(timezone=True), nullable=True),
        )

    if not table_exists("session_versions"):
        op.create_table(
            "session_versions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column(
                "workout_id",
                UUID(as_uuid=True),
                sa.ForeignKey("workouts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("exercises_json", JSONB, nullable=False),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("session_effort", sa.Integer(), nullable=True),
            sa.Column("tss", sa.Float(), nullable=True),
            sa.Column("summary_line", sa.Text(), nullable=True),
        )
        op.create_index("ix_session_versions_workout_saved", "session_versions", ["workout_id", "saved_at"])

    if not table_exists("pending_exercises"):
        op.create_table(
            "pending_exercises",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("normalized_name", sa.String(200), nullable=False, unique=True),
            sa.Column("display_name", sa.String(200), nullable=False),
            sa.Column(
                "first_seen_workout_id",
                UUID(as_uuid=True),
                sa.ForeignKey("workouts.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("occurrence_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
            sa.Column("closest_match", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if table_exists("pending_exercises"):
        op.drop_table("pending_exercises")
    if table_exists("session_versions"):
        op.drop_index("ix_session_versions_workout_saved", table_name="session_versions")
        op.drop_table("session_versions")
    if column_exists("workouts", "recompute_pending"):
        op.drop_column("workouts", "recompute_pending")
    if column_exists("workouts", "exercises_json"):
        op.drop_column("workouts", "exercises_json")