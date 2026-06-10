"""Add habit_logs full schema with log_date, log_week_start, value, notes, source, updated_at; cascade FKs; composite index.

Table docstring: Habit log entries. For daily_checkmark habits, one row per day checked (value=1). For weekly_count/minutes/quantity habits, one row per logged event with the contributed value. Week aggregation done at read time by summing values where log_week_start matches.

Revision ID: z9n0o1p2q3r4
Revises: y8m9n0o1p2q3
Create Date: 2026-06-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

from helpers import column_exists, table_exists, index_exists

revision: str = "z9n0o1p2q3r4"
down_revision: Union[str, None] = "y8m9n0o1p2q3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DOCSTRING = (
    "Habit log entries. For daily_checkmark habits, one row per day checked (value=1). "
    "For weekly_count/minutes/quantity habits, one row per logged event with the contributed value. "
    "Week aggregation done at read time by summing values where log_week_start matches."
)


def _constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = :table "
            "AND constraint_name = :name"
        ),
        {"table": table, "name": name},
    ).fetchone()
    return row is not None


def _drop_fks_to(from_table: str, referred_table: str) -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    fks = insp.get_foreign_keys(from_table)
    for fk in fks:
        if fk["referred_table"] == referred_table and fk.get("name"):
            op.drop_constraint(fk["name"], from_table, type_="foreignkey")


def upgrade() -> None:
    if not table_exists("habit_logs"):
        op.create_table(
            "habit_logs",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("habit_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("log_date", sa.Date(), nullable=False),
            sa.Column("log_week_start", sa.Date(), nullable=False),
            sa.Column(
                "value",
                sa.Numeric(10, 4),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "source",
                sa.String(50),
                nullable=False,
                server_default=sa.text("'manual'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("habit_id", "log_date", name="uq_habit_logs_habit_log_date"),
        )
        op.create_foreign_key(
            "habit_logs_habit_id_fkey", "habit_logs", "habits",
            ["habit_id"], ["id"], ondelete="CASCADE",
        )
        op.create_foreign_key(
            "habit_logs_user_id_fkey", "habit_logs", "users",
            ["user_id"], ["id"], ondelete="CASCADE",
        )
        op.create_index(
            "ix_habit_logs_habit_id_log_week_start",
            "habit_logs", ["habit_id", "log_week_start"],
        )
        return

    # ── Existing table: migrate idempotently ──────────────────────────────────

    # 1. Rename logged_date → log_date
    if column_exists("habit_logs", "logged_date") and not column_exists("habit_logs", "log_date"):
        op.alter_column("habit_logs", "logged_date", new_column_name="log_date")

    # 2. Add missing columns
    if not column_exists("habit_logs", "log_week_start"):
        op.add_column("habit_logs", sa.Column("log_week_start", sa.Date(), nullable=True))
        op.execute(
            "UPDATE habit_logs SET log_week_start = date_trunc('week', log_date)::date"
        )
        op.alter_column("habit_logs", "log_week_start", nullable=False)

    if not column_exists("habit_logs", "value"):
        op.add_column("habit_logs", sa.Column("value", sa.Numeric(10, 4), nullable=True))
        op.execute("UPDATE habit_logs SET value = 1")
        op.alter_column(
            "habit_logs", "value", nullable=False, server_default=sa.text("1")
        )

    if not column_exists("habit_logs", "notes"):
        op.add_column("habit_logs", sa.Column("notes", sa.Text(), nullable=True))

    if not column_exists("habit_logs", "source"):
        op.add_column("habit_logs", sa.Column("source", sa.String(50), nullable=True))
        op.execute("UPDATE habit_logs SET source = 'manual'")
        op.alter_column(
            "habit_logs", "source", nullable=False, server_default=sa.text("'manual'")
        )

    if not column_exists("habit_logs", "updated_at"):
        op.add_column(
            "habit_logs",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 3. Fix unique constraint — drop old (may reference logged_date or log_date), create new
    if _constraint_exists("habit_logs", "uq_habit_logs_habit_date"):
        op.drop_constraint("uq_habit_logs_habit_date", "habit_logs", type_="unique")
    if not _constraint_exists("habit_logs", "uq_habit_logs_habit_log_date"):
        op.create_unique_constraint(
            "uq_habit_logs_habit_log_date", "habit_logs", ["habit_id", "log_date"]
        )

    # 4. Upgrade FKs to CASCADE — drop existing and recreate with explicit names
    _drop_fks_to("habit_logs", "habits")
    if not _constraint_exists("habit_logs", "habit_logs_habit_id_fkey"):
        op.create_foreign_key(
            "habit_logs_habit_id_fkey", "habit_logs", "habits",
            ["habit_id"], ["id"], ondelete="CASCADE",
        )

    _drop_fks_to("habit_logs", "users")
    if not _constraint_exists("habit_logs", "habit_logs_user_id_fkey"):
        op.create_foreign_key(
            "habit_logs_user_id_fkey", "habit_logs", "users",
            ["user_id"], ["id"], ondelete="CASCADE",
        )

    # 5. Composite index
    if not index_exists("habit_logs", "ix_habit_logs_habit_id_log_week_start"):
        op.create_index(
            "ix_habit_logs_habit_id_log_week_start",
            "habit_logs", ["habit_id", "log_week_start"],
        )


def downgrade() -> None:
    if not table_exists("habit_logs"):
        return

    if index_exists("habit_logs", "ix_habit_logs_habit_id_log_week_start"):
        op.drop_index("ix_habit_logs_habit_id_log_week_start", table_name="habit_logs")

    if _constraint_exists("habit_logs", "uq_habit_logs_habit_log_date"):
        op.drop_constraint("uq_habit_logs_habit_log_date", "habit_logs", type_="unique")

    for col in ("updated_at", "source", "notes", "value", "log_week_start"):
        if column_exists("habit_logs", col):
            op.drop_column("habit_logs", col)

    if column_exists("habit_logs", "log_date") and not column_exists("habit_logs", "logged_date"):
        op.alter_column("habit_logs", "log_date", new_column_name="logged_date")
