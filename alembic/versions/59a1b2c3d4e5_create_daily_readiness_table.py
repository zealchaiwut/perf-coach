"""create daily_readiness table for computed readiness scores

Revision ID: 59a1b2c3d4e5
Revises: 38a0b1c2d3e4
Create Date: 2026-05-27 00:00:04.000000

Stores pre-computed daily readiness scores (0–100) alongside per-signal
additive contributions (hrv, rhr, sleep, energy) in a JSONB column.
One row per user per day, computed by the readiness job from daily_metrics.

Includes:
- FK to users with CASCADE delete
- FK to daily_metrics with SET NULL on delete (score survives metric deletion)
- Unique constraint on (user_id, date)
- CHECK constraint: score in [0, 100]
- Index on (user_id, date DESC) for time-series queries

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "59a1b2c3d4e5"
down_revision: Union[str, None] = "38a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("daily_readiness"):
        return

    op.create_table(
        "daily_readiness",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("daily_metric_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_foreign_key(
        "daily_readiness_user_id_fkey",
        "daily_readiness",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        "daily_readiness_daily_metric_id_fkey",
        "daily_readiness",
        "daily_metrics",
        ["daily_metric_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        "ALTER TABLE daily_readiness ADD CONSTRAINT uq_daily_readiness_user_date "
        "UNIQUE (user_id, date)"
    )

    op.execute(
        "ALTER TABLE daily_readiness ADD CONSTRAINT ck_daily_readiness_score_range "
        "CHECK (score >= 0 AND score <= 100)"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_daily_readiness_user_date "
        "ON daily_readiness (user_id, date DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_daily_readiness_user_date")
    if table_exists("daily_readiness"):
        op.drop_table("daily_readiness")
