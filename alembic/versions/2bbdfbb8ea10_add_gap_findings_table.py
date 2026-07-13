"""add gap_findings table (issue #1370)

Revision ID: 2bbdfbb8ea10
Revises: dccd66f7b819
Create Date: 2026-07-14 00:00:45.416633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, column_exists, index_exists

revision: str = "2bbdfbb8ea10"
down_revision: Union[str, Sequence[str], None] = "dccd66f7b819"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("gap_findings"):
        return

    op.create_table(
        "gap_findings",
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
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("severity", sa.Integer, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("evidence", postgresql.JSONB, nullable=False),
        sa.Column("target", sa.String(100), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "week_start", "code", name="uq_gap_findings_user_week_code"),
        sa.CheckConstraint("severity IN (1, 2, 3)", name="ck_gap_findings_severity"),
        sa.CheckConstraint(
            "status IN ('active', 'accepted', 'dismissed')",
            name="ck_gap_findings_status",
        ),
    )

    if not index_exists("gap_findings", "ix_gap_findings_user_week_start"):
        op.create_index(
            "ix_gap_findings_user_week_start",
            "gap_findings",
            ["user_id", "week_start"],
        )


def downgrade() -> None:
    if not table_exists("gap_findings"):
        return
    op.drop_index("ix_gap_findings_user_week_start", table_name="gap_findings")
    op.drop_table("gap_findings")
