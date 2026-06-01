"""Standalone post-workout journal. workout_id is nullable to allow rest-day or pre-workout entries; future tickets will auto-link entries to workouts by date when possible. RPE is the only structured field — Borg scale 1-10 (1=very light, 10=max effort). Everything else is free text by design.

Revision ID: i2c3d4e5f6a7
Revises: h1b2c3d4e5f6
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from helpers import table_exists, index_exists

revision = "i2c3d4e5f6a7"
down_revision = "h1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("workout_feel"):
        return

    op.create_table(
        "workout_feel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feel_date", sa.Date, nullable=False),
        sa.Column("workout_id", UUID(as_uuid=True), sa.ForeignKey("workouts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rpe_1_to_10", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    if not index_exists("workout_feel", "ix_workout_feel_user_feel_date"):
        op.create_index(
            "ix_workout_feel_user_feel_date",
            "workout_feel",
            ["user_id", "feel_date"],
        )


def downgrade():
    op.drop_index("ix_workout_feel_user_feel_date", table_name="workout_feel")
    op.drop_table("workout_feel")
