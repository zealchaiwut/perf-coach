"""add_cp_history_table

Revision ID: c4b5ed9f6d24
Revises: 1fbab07a5c4d
Create Date: 2026-11-22

Revamp P6-3 (#1877): dated history of confirmed Critical Power changes. The
current CP stays on user_preferences.ftp_w; this table is the audit trail.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "c4b5ed9f6d24"
down_revision: Union[str, Sequence[str], None] = "1fbab07a5c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("cp_history"):
        return
    op.create_table(
        "cp_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cp_w", sa.Integer(), nullable=False),
        sa.Column("previous_cp_w", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_cp_history_user_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_cp_history_user_date", "cp_history", ["user_id", "effective_date"])


def downgrade() -> None:
    if not table_exists("cp_history"):
        return
    op.drop_index("ix_cp_history_user_date", table_name="cp_history")
    op.drop_table("cp_history")
