"""add_performance_score_history

Revision ID: 129d863fa625
Revises: cea323ec2396
Create Date: 2026-07-13

Add performance_score_history table for persisting daily endurance/speed scores
with formula version stamps (issue #1361/#1365). Used to compute block deltas
on the absolute scale rather than the in-request relative trend[].
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "129d863fa625"
down_revision: Union[str, Sequence[str], None] = "cea323ec2396"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("performance_score_history"):
        return

    op.create_table(
        "performance_score_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_date", sa.Date(), nullable=False),
        sa.Column("endurance", sa.Float(), nullable=True),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("formula_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "score_date", "formula_version",
            name="uq_performance_score_history_user_date_version",
        ),
    )
    op.create_foreign_key(
        "performance_score_history_user_id_fkey",
        "performance_score_history",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    if not index_exists("performance_score_history", "ix_performance_score_history_user_date"):
        op.create_index(
            "ix_performance_score_history_user_date",
            "performance_score_history",
            ["user_id", "score_date"],
        )


def downgrade() -> None:
    if not table_exists("performance_score_history"):
        return
    if index_exists("performance_score_history", "ix_performance_score_history_user_date"):
        op.drop_index(
            "ix_performance_score_history_user_date",
            table_name="performance_score_history",
        )
    op.drop_table("performance_score_history")
