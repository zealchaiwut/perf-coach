"""add summary_cache table for durable summary/performance L2 cache

Revision ID: c348d3b407f6
Revises: 5d1ce0a241f1
Create Date: 2026-07-02 14:11:45.490695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = 'c348d3b407f6'
down_revision: Union[str, Sequence[str], None] = '5d1ce0a241f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the durable summary/performance L2 cache table (idempotent)."""
    if not table_exists("summary_cache"):
        op.create_table(
            "summary_cache",
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("cache_key", sa.Text(), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("user_id", "cache_key"),
        )


def downgrade() -> None:
    """Drop the summary_cache table (idempotent)."""
    if table_exists("summary_cache"):
        op.drop_table("summary_cache")
