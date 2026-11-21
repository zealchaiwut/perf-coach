"""create performance_queue_items

Revision ID: 8d8cd37743d3
Revises: 25e2032a3208
Create Date: 2026-11-21 23:03:47.089980

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import index_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '8d8cd37743d3'
down_revision: Union[str, Sequence[str], None] = '25e2032a3208'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Suggestion records from the Performance focus queue, consumed by P3-10 (P4-7)."""
    if not table_exists("performance_queue_items"):
        op.create_table(
            "performance_queue_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("axis", sa.String(30), nullable=False),
            sa.Column("template_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                      server_default=sa.text("'[]'::jsonb")),
            sa.Column("tss_estimate", sa.Float(), nullable=True),
            sa.Column("earliest_week", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'queued'")),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint(
                "status IN ('queued', 'applied', 'cancelled')",
                name="ck_performance_queue_items_status",
            ),
        )
    if not index_exists("performance_queue_items", "ix_performance_queue_items_user_status"):
        op.create_index(
            "ix_performance_queue_items_user_status",
            "performance_queue_items",
            ["user_id", "status", "earliest_week"],
        )


def downgrade() -> None:
    if not table_exists("performance_queue_items"):
        return
    if index_exists("performance_queue_items", "ix_performance_queue_items_user_status"):
        op.drop_index("ix_performance_queue_items_user_status", table_name="performance_queue_items")
    op.drop_table("performance_queue_items")
