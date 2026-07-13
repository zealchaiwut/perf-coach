"""Add muscle_load_daily table for TSS-weighted muscle group ledger (issue #1367).

Revision ID: a4cf1cbd5020
Revises: 24d017bf47ed
Create Date: 2026-07-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, table_exists, index_exists

revision: str = "a4cf1cbd5020"
down_revision: Union[str, None] = "24d017bf47ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("muscle_load_daily"):
        return

    op.create_table(
        "muscle_load_daily",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("load_date", sa.Date, nullable=False),
        sa.Column("muscle_group", sa.String(30), nullable=False),
        sa.Column("load", sa.Numeric(10, 4), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "load_date", "muscle_group", "source",
            name="uq_muscle_load_daily_user_date_group_source",
        ),
        sa.CheckConstraint(
            "source IN ('strength', 'run', 'plyo')",
            name="ck_muscle_load_daily_source",
        ),
    )
    op.create_foreign_key(
        "muscle_load_daily_user_id_fkey",
        "muscle_load_daily",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_muscle_load_daily_user_date",
        "muscle_load_daily",
        ["user_id", "load_date"],
    )


def downgrade() -> None:
    if not table_exists("muscle_load_daily"):
        return

    if index_exists("muscle_load_daily", "ix_muscle_load_daily_user_date"):
        op.drop_index("ix_muscle_load_daily_user_date", table_name="muscle_load_daily")

    op.drop_table("muscle_load_daily")
