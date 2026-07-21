"""add_plan_drafts

Revision ID: 71b8f0d766c0
Revises: a384a3b4727d
Create Date: 2026-07-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "71b8f0d766c0"
down_revision: Union[str, Sequence[str], None] = "a384a3b4727d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("plan_drafts"):
        op.create_table(
            "plan_drafts",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("week_start", sa.Date(), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column("facts_signature", sa.String(64), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'fresh'")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "week_start", name="uq_plan_drafts_user_week"),
            sa.CheckConstraint(
                "status IN ('fresh', 'outdated', 'applied', 'expired')",
                name="ck_plan_drafts_status",
            ),
        )
        op.create_index("ix_plan_drafts_user_week", "plan_drafts", ["user_id", "week_start"])


def downgrade() -> None:
    if table_exists("plan_drafts"):
        op.drop_table("plan_drafts")
