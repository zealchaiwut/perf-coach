"""add_performance_score_history

Creates performance_score_history table to persist endurance/speed scores
with formula version stamps. Unique on (user_id, score_date, formula_version);
upsert on recompute. Tracked by issue #1361.

Revision ID: 1f0306497830
Revises: cea323ec2396
Create Date: 2026-07-13 09:47:46.418865

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import table_exists, index_exists


# revision identifiers, used by Alembic.
revision: str = '1f0306497830'
down_revision: Union[str, Sequence[str], None] = 'cea323ec2396'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("performance_score_history"):
        return

    op.create_table(
        "performance_score_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score_date", sa.Date, nullable=False),
        sa.Column("endurance", sa.Float, nullable=True),
        sa.Column("speed", sa.Float, nullable=True),
        sa.Column("formula_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "score_date", "formula_version", name="uq_perf_score_history_user_date_version"),
    )

    if not index_exists("performance_score_history", "ix_perf_score_history_user_date"):
        op.create_index(
            "ix_perf_score_history_user_date",
            "performance_score_history",
            ["user_id", "score_date"],
        )


def downgrade() -> None:
    if table_exists("performance_score_history"):
        op.drop_index("ix_perf_score_history_user_date", table_name="performance_score_history")
        op.drop_table("performance_score_history")
