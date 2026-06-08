"""Add workout_templates table for saving exercise lists as reusable templates.

Revision ID: q0e1f2a3b4c5
Revises: p9d0e1f2a3b4
Create Date: 2026-06-04

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from helpers import table_exists, index_exists

revision = "q0e1f2a3b4c5"
down_revision = "p9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    if not table_exists("workout_templates"):
        op.create_table(
            "workout_templates",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("exercises", JSONB, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
    if not index_exists("workout_templates", "ix_workout_templates_user_id"):
        op.create_index(
            "ix_workout_templates_user_id",
            "workout_templates",
            ["user_id"],
        )


def downgrade():
    if index_exists("workout_templates", "ix_workout_templates_user_id"):
        op.drop_index("ix_workout_templates_user_id", table_name="workout_templates")
    if table_exists("workout_templates"):
        op.drop_table("workout_templates")
