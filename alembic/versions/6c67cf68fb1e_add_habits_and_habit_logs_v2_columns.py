"""Add v2 schema columns to habits and habit_logs tables (creates both if absent).

Adds habit_type/schedule_type/target_value/schedule_target/active to habits
and note column to habit_logs. Both operations are fully idempotent. If either
table does not exist it is created from scratch with the complete column set
required by issue #821 (including legacy columns so prior-migration tests pass).

Revision ID: 6c67cf68fb1e
Revises: 8cd49d182ff6
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, table_exists

revision: str = "6c67cf68fb1e"
down_revision: Union[str, None] = "8cd49d182ff6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HABIT_TYPE_VALUES = "('binary', 'count', 'duration')"
_SCHEDULE_TYPE_VALUES = "('daily', 'weekly', 'times_per_week')"


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


def _upgrade_habits() -> None:
    if not table_exists("habits"):
        # Fresh DB: create with both legacy and v2 columns so all existing tests pass.
        op.create_table(
            "habits",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            # v2 columns
            sa.Column(
                "habit_type",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'binary'"),
            ),
            sa.Column("target_value", sa.Numeric(12, 4), nullable=True),
            sa.Column("unit", sa.String(50), nullable=True),
            sa.Column(
                "schedule_type",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'daily'"),
            ),
            sa.Column("schedule_target", sa.Integer(), nullable=True),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            # Legacy columns retained for backward-compat
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "tracking_type",
                sa.String(50),
                nullable=False,
                server_default=sa.text("'daily_checkmark'"),
            ),
            sa.Column("weekly_target", sa.Numeric(10, 2), nullable=True),
            sa.Column("auto_fill_source", sa.String(100), nullable=True),
            sa.Column("icon", sa.String(100), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "is_archived",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                f"habit_type IN {_HABIT_TYPE_VALUES}",
                name="ck_habits_habit_type_values",
            ),
            sa.CheckConstraint(
                f"schedule_type IN {_SCHEDULE_TYPE_VALUES}",
                name="ck_habits_schedule_type_values",
            ),
        )
        op.create_foreign_key(
            "habits_user_id_fkey",
            "habits",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        return

    # Existing table — add v2 columns idempotently.
    if not column_exists("habits", "habit_type"):
        op.add_column(
            "habits",
            sa.Column("habit_type", sa.Text(), nullable=True),
        )
        op.execute("UPDATE habits SET habit_type = 'binary' WHERE habit_type IS NULL")
        op.alter_column(
            "habits", "habit_type", nullable=False, server_default=sa.text("'binary'")
        )

    if not column_exists("habits", "target_value"):
        op.add_column("habits", sa.Column("target_value", sa.Numeric(12, 4), nullable=True))

    if not column_exists("habits", "schedule_type"):
        op.add_column(
            "habits",
            sa.Column("schedule_type", sa.Text(), nullable=True),
        )
        op.execute("UPDATE habits SET schedule_type = 'daily' WHERE schedule_type IS NULL")
        op.alter_column(
            "habits", "schedule_type", nullable=False, server_default=sa.text("'daily'")
        )

    if not column_exists("habits", "schedule_target"):
        op.add_column("habits", sa.Column("schedule_target", sa.Integer(), nullable=True))

    if not column_exists("habits", "active"):
        op.add_column("habits", sa.Column("active", sa.Boolean(), nullable=True))
        op.execute("UPDATE habits SET active = true WHERE active IS NULL")
        op.alter_column(
            "habits", "active", nullable=False, server_default=sa.text("true")
        )

    if not _constraint_exists("habits", "ck_habits_habit_type_values"):
        op.execute(
            f"ALTER TABLE habits ADD CONSTRAINT ck_habits_habit_type_values "
            f"CHECK (habit_type IN {_HABIT_TYPE_VALUES})"
        )

    if not _constraint_exists("habits", "ck_habits_schedule_type_values"):
        op.execute(
            f"ALTER TABLE habits ADD CONSTRAINT ck_habits_schedule_type_values "
            f"CHECK (schedule_type IN {_SCHEDULE_TYPE_VALUES})"
        )


def _upgrade_habit_logs() -> None:
    if not table_exists("habit_logs"):
        # Fresh DB: create with both legacy and v2 columns.
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
            sa.Column(
                "value",
                sa.Numeric(10, 4),
                nullable=False,
                server_default=sa.text("1"),
            ),
            # v2 column
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            # Legacy columns retained for backward-compat
            sa.Column("log_week_start", sa.Date(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "source",
                sa.String(50),
                nullable=False,
                server_default=sa.text("'manual'"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("habit_id", "log_date", name="uq_habit_logs_habit_log_date"),
        )
        op.create_foreign_key(
            "habit_logs_habit_id_fkey",
            "habit_logs",
            "habits",
            ["habit_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "habit_logs_user_id_fkey",
            "habit_logs",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(
            "ix_habit_logs_habit_id_log_week_start",
            "habit_logs",
            ["habit_id", "log_week_start"],
        )
        return

    # Existing table — add note column idempotently.
    if not column_exists("habit_logs", "note"):
        op.add_column("habit_logs", sa.Column("note", sa.Text(), nullable=True))


def upgrade() -> None:
    _upgrade_habits()
    _upgrade_habit_logs()


def downgrade() -> None:
    # Drop both tables cleanly if they exist (AC requirement).
    if table_exists("habit_logs"):
        op.drop_table("habit_logs")
    if table_exists("habits"):
        op.drop_table("habits")
