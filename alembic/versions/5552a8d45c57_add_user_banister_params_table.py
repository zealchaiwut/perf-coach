"""add_user_banister_params_table

Adds user_banister_params table for per-user Banister model parameter
storage with versioned history (issue #1204).  Each row is an immutable
version snapshot; prior rows are never overwritten.

Revision ID: 5552a8d45c57
Revises: 1895a1396795
Create Date: 2026-07-01 11:36:21.092306

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "5552a8d45c57"
down_revision: Union[str, None] = "1895a1396795"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("user_banister_params"):
        return

    op.create_table(
        "user_banister_params",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tau1", sa.Float(), nullable=False),
        sa.Column("tau2", sa.Float(), nullable=False),
        sa.Column("k1", sa.Float(), nullable=False),
        sa.Column("k2", sa.Float(), nullable=False),
        sa.Column("fitted_at", sa.DateTime(timezone=True), nullable=False),
    )

    if not index_exists("user_banister_params", "ix_user_banister_params_user_fitted_at"):
        op.create_index(
            "ix_user_banister_params_user_fitted_at",
            "user_banister_params",
            ["user_id", "fitted_at"],
        )


def downgrade() -> None:
    if not table_exists("user_banister_params"):
        return

    if index_exists("user_banister_params", "ix_user_banister_params_user_fitted_at"):
        op.drop_index(
            "ix_user_banister_params_user_fitted_at",
            table_name="user_banister_params",
        )

    op.drop_table("user_banister_params")
