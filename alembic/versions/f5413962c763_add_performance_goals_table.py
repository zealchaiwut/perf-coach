"""add_performance_goals_table

Revision ID: f5413962c763
Revises: d74840f7d00e
Create Date: 2026-07-17 13:58:05.646231

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, column_exists, index_exists

# revision identifiers, used by Alembic.
revision: str = 'f5413962c763'
down_revision: Union[str, Sequence[str], None] = 'd74840f7d00e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("performance_goals"):
        op.create_table(
            "performance_goals",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("race_distance", sa.String(20), nullable=False),
            sa.Column("target_time", sa.Integer, nullable=False),
            sa.Column("race_date", sa.Date, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "active",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.CheckConstraint(
                "race_distance IN ('5k', '10k', 'half', 'marathon')",
                name="ck_performance_goals_race_distance_values",
            ),
        )

    if not index_exists("performance_goals", "ix_performance_goals_user_id"):
        op.create_index(
            "ix_performance_goals_user_id",
            "performance_goals",
            ["user_id"],
        )


def downgrade() -> None:
    if not table_exists("performance_goals"):
        return
    if index_exists("performance_goals", "ix_performance_goals_user_id"):
        op.drop_index("ix_performance_goals_user_id", table_name="performance_goals")
    op.drop_table("performance_goals")
