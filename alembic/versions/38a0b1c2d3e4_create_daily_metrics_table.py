"""create daily_metrics table for rhr, hrv, sleep, energy, mood

Revision ID: 38a0b1c2d3e4
Revises: e5f6a7b8c9d0
Create Date: 2026-05-27 00:00:03.000000

Creates a daily_metrics table — one row per user per day — to store
recovery and wellness signals: resting heart rate, HRV, sleep hours,
sleep quality, energy, and mood. Separate from weight_entries by design.

Includes:
- FK to users with CASCADE delete
- Unique constraint on (user_id, metric_date)
- CHECK constraints on all bounded numeric columns
- Index on (user_id, metric_date DESC) for time-series queries
- set_updated_at() trigger function + BEFORE UPDATE trigger to keep
  updated_at current automatically

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "38a0b1c2d3e4"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("daily_metrics"):
        op.create_table(
            "daily_metrics",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("metric_date", sa.Date(), nullable=False),
            sa.Column("resting_hr", sa.Integer(), nullable=True),
            sa.Column("hrv", sa.Integer(), nullable=True),
            sa.Column("sleep_hours", sa.Numeric(3, 1), nullable=True),
            sa.Column("sleep_quality", sa.Integer(), nullable=True),
            sa.Column("energy", sa.Integer(), nullable=True),
            sa.Column("mood", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
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
            sa.PrimaryKeyConstraint("id"),
        )

        # FK with CASCADE (explicit to work around Neon ignoring inline ondelete options)
        op.create_foreign_key(
            "daily_metrics_user_id_fkey",
            "daily_metrics",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # Unique constraint: one row per user per day
        op.execute(
            "ALTER TABLE daily_metrics ADD CONSTRAINT uq_daily_metrics_user_date "
            "UNIQUE (user_id, metric_date)"
        )

        # CHECK constraints via raw SQL to guarantee enforcement on Neon
        op.execute(
            "ALTER TABLE daily_metrics ADD CONSTRAINT ck_daily_metrics_resting_hr "
            "CHECK (resting_hr IS NULL OR (resting_hr >= 20 AND resting_hr <= 200))"
        )
        op.execute(
            "ALTER TABLE daily_metrics ADD CONSTRAINT ck_daily_metrics_hrv "
            "CHECK (hrv IS NULL OR (hrv >= 0 AND hrv <= 300))"
        )
        op.execute(
            "ALTER TABLE daily_metrics ADD CONSTRAINT ck_daily_metrics_sleep_hours "
            "CHECK (sleep_hours IS NULL OR (sleep_hours >= 0 AND sleep_hours <= 24))"
        )
        op.execute(
            "ALTER TABLE daily_metrics ADD CONSTRAINT ck_daily_metrics_sleep_quality "
            "CHECK (sleep_quality IS NULL OR (sleep_quality >= 1 AND sleep_quality <= 5))"
        )
        op.execute(
            "ALTER TABLE daily_metrics ADD CONSTRAINT ck_daily_metrics_energy "
            "CHECK (energy IS NULL OR (energy >= 1 AND energy <= 5))"
        )
        op.execute(
            "ALTER TABLE daily_metrics ADD CONSTRAINT ck_daily_metrics_mood "
            "CHECK (mood IS NULL OR (mood >= 1 AND mood <= 5))"
        )

    # Index for time-series queries: most-recent-first per user
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_daily_metrics_user_date "
        "ON daily_metrics (user_id, metric_date DESC)"
    )

    # Trigger function to keep updated_at current on every UPDATE
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.triggers
                WHERE trigger_name = 'trg_daily_metrics_updated_at'
                  AND event_object_table = 'daily_metrics'
            ) THEN
                CREATE TRIGGER trg_daily_metrics_updated_at
                BEFORE UPDATE ON daily_metrics
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_daily_metrics_updated_at ON daily_metrics")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP INDEX IF EXISTS ix_daily_metrics_user_date")
    if table_exists("daily_metrics"):
        op.drop_table("daily_metrics")
