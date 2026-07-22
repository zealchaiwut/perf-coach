"""add_daily_briefs_table

Revision ID: a384a3b4727d
Revises: d35f3915950e
Create Date: 2026-07-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "a384a3b4727d"
down_revision: Union[str, Sequence[str], None] = "d35f3915950e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("daily_briefs"):
        return
    op.create_table(
        "daily_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brief_date", sa.Date(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'fallback'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "brief_date", name="uq_daily_briefs_user_date"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_daily_briefs_user_date",
        "daily_briefs",
        ["user_id", "brief_date"],
    )


def downgrade() -> None:
    if not table_exists("daily_briefs"):
        return
    if index_exists("daily_briefs", "ix_daily_briefs_user_date"):
        op.drop_index("ix_daily_briefs_user_date", table_name="daily_briefs")
    op.drop_table("daily_briefs")
