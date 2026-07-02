"""add planned_sessions

Revision ID: 6ce18fda0701
Revises: d8c453113f1d
Create Date: 2026-07-02 16:04:01.363023

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = '6ce18fda0701'
down_revision: Union[str, Sequence[str], None] = 'd8c453113f1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the planned_sessions table for the new Plan tab (idempotent)."""
    if not table_exists("planned_sessions"):
        op.create_table(
            "planned_sessions",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("planned_date", sa.Date(), nullable=False),
            sa.Column("session_type", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=True),
            sa.Column("structure", postgresql.JSONB(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'planned'"),
            ),
            sa.Column("matched_workout_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["matched_workout_id"], ["workouts.id"], ondelete="SET NULL"
            ),
        )
        op.create_index(
            "ix_planned_sessions_user_id", "planned_sessions", ["user_id"]
        )
        op.create_index(
            "ix_planned_sessions_planned_date", "planned_sessions", ["planned_date"]
        )
        op.create_index(
            "ix_planned_sessions_user_date",
            "planned_sessions",
            ["user_id", "planned_date"],
        )


def downgrade() -> None:
    """Drop the planned_sessions table (idempotent)."""
    if table_exists("planned_sessions"):
        op.drop_table("planned_sessions")
