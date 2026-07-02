"""add_strength_sessions_table

Revision ID: 6de228e34220
Revises: e3f1c0da097c
Create Date: 2026-06-30 16:15:04.178092

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists


# revision identifiers, used by Alembic.
revision: str = '6de228e34220'
down_revision: Union[str, Sequence[str], None] = 'e3f1c0da097c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("strength_sessions"):
        return

    op.create_table(
        "strength_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("load", sa.Numeric(8, 2), nullable=True),
        sa.Column("session_rpe", sa.Integer(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_strength_sessions_user_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("sets IS NULL OR sets > 0", name="ck_strength_sessions_sets_positive"),
        sa.CheckConstraint("reps IS NULL OR reps > 0", name="ck_strength_sessions_reps_positive"),
        sa.CheckConstraint("load IS NULL OR load >= 0", name="ck_strength_sessions_load_non_negative"),
        sa.CheckConstraint(
            "session_rpe IS NULL OR (session_rpe >= 1 AND session_rpe <= 10)",
            name="ck_strength_sessions_rpe_range",
        ),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_strength_sessions_duration_positive",
        ),
    )

    if not index_exists("strength_sessions", "ix_strength_sessions_user_date"):
        op.create_index(
            "ix_strength_sessions_user_date",
            "strength_sessions",
            ["user_id", "session_date"],
        )


def downgrade() -> None:
    if not table_exists("strength_sessions"):
        return

    if index_exists("strength_sessions", "ix_strength_sessions_user_date"):
        op.drop_index("ix_strength_sessions_user_date", table_name="strength_sessions")

    op.drop_table("strength_sessions")
