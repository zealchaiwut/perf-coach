"""Add weight_plans table with phase/goal/rate columns for structured weight planning.

Revision ID: 64d8ad2d9a42
Revises: 6c67cf68fb1e
Create Date: 2026-06-21 19:36:25.199346
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "64d8ad2d9a42"
down_revision: Union[str, None] = "6c67cf68fb1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("weight_plans"):
        op.create_table(
            "weight_plans",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("start_weight_kg", sa.Numeric(6, 2), nullable=False),
            sa.Column("goal_weight_kg", sa.Numeric(6, 2), nullable=False),
            sa.Column("goal_date", sa.Date(), nullable=True),
            sa.Column("target_rate_kg_per_week", sa.Numeric(4, 2), nullable=True),
            sa.Column(
                "phase",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'cut'"),
            ),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="weight_plans_user_id_fkey",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="weight_plans_pkey"),
        )

    if not index_exists("weight_plans", "ix_weight_plans_user_id"):
        op.create_index(
            "ix_weight_plans_user_id",
            "weight_plans",
            ["user_id"],
        )


def downgrade() -> None:
    if table_exists("weight_plans"):
        if index_exists("weight_plans", "ix_weight_plans_user_id"):
            op.drop_index("ix_weight_plans_user_id", table_name="weight_plans")
        op.drop_table("weight_plans")
