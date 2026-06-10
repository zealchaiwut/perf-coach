"""Unified habits table. Replaces separate weekly-target concept. Each habit can be manual (daily_checkmark with weekly_target as days/week) or auto-fill from workouts. Manual entries logged via habit_logs (separate table, see next ticket).

Revision ID: y8m9n0o1p2q3
Revises: x7l8m9n0o1p2
Create Date: 2026-06-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, table_exists

revision: str = "y8m9n0o1p2q3"
down_revision: Union[str, None] = "x7l8m9n0o1p2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRACKING_TYPES_SQL = "('daily_checkmark','weekly_count','weekly_minutes','weekly_quantity')"
_AUTO_FILL_SOURCES_SQL = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km')"
)


def _constraint_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = 'habits' "
            "AND constraint_name = :name"
        ),
        {"name": name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    if not table_exists("habits"):
        # Fresh DB: create the full unified table from scratch
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
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "tracking_type",
                sa.String(50),
                nullable=False,
                server_default=sa.text("'daily_checkmark'"),
            ),
            sa.Column("weekly_target", sa.Numeric(10, 2), nullable=True),
            sa.Column("unit", sa.String(50), nullable=True),
            sa.Column("auto_fill_source", sa.String(100), nullable=True),
            sa.Column("icon", sa.String(100), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column(
                "sort_order",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "is_archived",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            # Legacy columns for backward-compat
            sa.Column(
                "display_order",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_foreign_key(
            "habits_user_id_fkey",
            "habits",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.execute(
            f"ALTER TABLE habits ADD CONSTRAINT ck_habits_tracking_type "
            f"CHECK (tracking_type IN {_TRACKING_TYPES_SQL})"
        )
        op.execute(
            f"ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
            f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_AUTO_FILL_SOURCES_SQL})"
        )
        return

    # Existing habits table — add new columns idempotently and backfill
    if not column_exists("habits", "description"):
        op.add_column("habits", sa.Column("description", sa.Text, nullable=True))

    if not column_exists("habits", "tracking_type"):
        op.add_column(
            "habits",
            sa.Column("tracking_type", sa.String(50), nullable=True),
        )
        op.execute(
            "UPDATE habits SET tracking_type = 'daily_checkmark' WHERE tracking_type IS NULL"
        )
        op.alter_column(
            "habits",
            "tracking_type",
            nullable=False,
            server_default=sa.text("'daily_checkmark'"),
        )

    if not column_exists("habits", "weekly_target"):
        op.add_column(
            "habits", sa.Column("weekly_target", sa.Numeric(10, 2), nullable=True)
        )

    if not column_exists("habits", "unit"):
        op.add_column("habits", sa.Column("unit", sa.String(50), nullable=True))

    if not column_exists("habits", "auto_fill_source"):
        op.add_column(
            "habits", sa.Column("auto_fill_source", sa.String(100), nullable=True)
        )

    if not column_exists("habits", "icon"):
        op.add_column("habits", sa.Column("icon", sa.String(100), nullable=True))

    if not column_exists("habits", "color"):
        op.add_column("habits", sa.Column("color", sa.String(20), nullable=True))

    if not column_exists("habits", "sort_order"):
        op.add_column(
            "habits", sa.Column("sort_order", sa.Integer, nullable=True)
        )
        op.execute("UPDATE habits SET sort_order = COALESCE(display_order, 0)")
        op.alter_column(
            "habits",
            "sort_order",
            nullable=False,
            server_default=sa.text("0"),
        )

    if not column_exists("habits", "is_archived"):
        op.add_column(
            "habits", sa.Column("is_archived", sa.Boolean, nullable=True)
        )
        op.execute(
            "UPDATE habits SET is_archived = (archived_at IS NOT NULL)"
        )
        op.alter_column(
            "habits",
            "is_archived",
            nullable=False,
            server_default=sa.text("false"),
        )

    if not column_exists("habits", "updated_at"):
        op.add_column(
            "habits",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    # Upgrade FK to CASCADE if not already
    if _constraint_exists("habits_user_id_fkey"):
        op.drop_constraint("habits_user_id_fkey", "habits", type_="foreignkey")
    op.create_foreign_key(
        "habits_user_id_fkey",
        "habits",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add check constraints via raw SQL (idempotent)
    if not _constraint_exists("ck_habits_tracking_type"):
        op.execute(
            f"ALTER TABLE habits ADD CONSTRAINT ck_habits_tracking_type "
            f"CHECK (tracking_type IN {_TRACKING_TYPES_SQL})"
        )

    if not _constraint_exists("ck_habits_auto_fill_source"):
        op.execute(
            f"ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
            f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_AUTO_FILL_SOURCES_SQL})"
        )


def downgrade() -> None:
    if not table_exists("habits"):
        return

    for constraint in ("ck_habits_auto_fill_source", "ck_habits_tracking_type"):
        if _constraint_exists(constraint):
            op.drop_constraint(constraint, "habits")

    for col in (
        "updated_at", "is_archived", "sort_order", "color", "icon",
        "auto_fill_source", "unit", "weekly_target", "tracking_type", "description",
    ):
        if column_exists("habits", col):
            op.drop_column("habits", col)
