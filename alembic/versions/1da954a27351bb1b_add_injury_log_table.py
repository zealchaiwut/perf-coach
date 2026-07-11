"""Add injury_log table for injury/illness/niggle tracking (issue #1350).

Revision ID: 1da954a27351bb1b
Revises: 8b73d5c83348
Create Date: 2026-07-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, table_exists, index_exists

revision: str = "1da954a27351bb1b"
down_revision: Union[str, None] = "8b73d5c83348"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("injury_log"):
        return

    op.create_table(
        "injury_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("body_area", sa.String(100), nullable=True),
        sa.Column("severity", sa.Integer, nullable=False),
        sa.Column("started_on", sa.Date, nullable=False),
        sa.Column("ended_on", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('injury', 'illness', 'niggle')",
            name="ck_injury_log_kind",
        ),
        sa.CheckConstraint(
            "severity IN (1, 2, 3)",
            name="ck_injury_log_severity",
        ),
        sa.CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on",
            name="ck_injury_log_ended_after_started",
        ),
    )
    op.create_foreign_key(
        "injury_log_user_id_fkey",
        "injury_log",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_injury_log_user_started_on",
        "injury_log",
        ["user_id", "started_on"],
    )


def downgrade() -> None:
    if not table_exists("injury_log"):
        return

    if index_exists("injury_log", "ix_injury_log_user_started_on"):
        op.drop_index("ix_injury_log_user_started_on", table_name="injury_log")

    op.drop_table("injury_log")
