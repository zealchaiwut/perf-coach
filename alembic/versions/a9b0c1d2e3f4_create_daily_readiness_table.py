"""create daily_readiness table for computed readiness scores

Revision ID: a9b0c1d2e3f4
Revises: f6a7b8c9d0e1
Create Date: 2026-05-27 00:00:04.000000

Stores one readiness score row per (user_id, date). The score is derived
from daily_metrics via the HRV CV approach documented in
services/readiness/README.md.

Includes:
- FK to users with CASCADE delete
- FK to daily_metrics with SET NULL on delete (score remains even if source row
  is deleted)
- Unique constraint on (user_id, date)
- CHECK constraint score in [0, 100]
- JSONB components column for per-signal breakdown
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("daily_readiness"):
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("daily_readiness"):
        op.drop_table("daily_readiness")
