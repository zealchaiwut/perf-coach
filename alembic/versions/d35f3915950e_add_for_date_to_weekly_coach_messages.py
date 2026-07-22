"""add_for_date_to_weekly_coach_messages

Revision ID: d35f3915950e
Revises: f2334eacc205
Create Date: 2026-07-18

Daily coach persistence: add for_date, unique (user_id, for_date), keep
for_week denormalized for display. Drop week-only uniqueness so multiple
days in the same ISO week can coexist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import table_exists, column_exists, index_exists

revision: str = "d35f3915950e"
down_revision: Union[str, Sequence[str], None] = "f2334eacc205"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade() -> None:
    if not table_exists("weekly_coach_messages"):
        return

    if not column_exists("weekly_coach_messages", "for_date"):
        op.add_column(
            "weekly_coach_messages",
            sa.Column("for_date", sa.Date(), nullable=True),
        )

    # Backfill from generated_at (UTC date) when missing.
    op.execute(
        sa.text(
            "UPDATE weekly_coach_messages "
            "SET for_date = (generated_at AT TIME ZONE 'UTC')::date "
            "WHERE for_date IS NULL"
        )
    )

    # Collapse duplicates that would violate (user_id, for_date): keep newest.
    op.execute(
        sa.text(
            """
            DELETE FROM weekly_coach_messages a
            USING weekly_coach_messages b
            WHERE a.user_id = b.user_id
              AND a.for_date = b.for_date
              AND a.generated_at < b.generated_at
            """
        )
    )

    op.alter_column(
        "weekly_coach_messages",
        "for_date",
        existing_type=sa.Date(),
        nullable=False,
    )

    if _constraint_exists("weekly_coach_messages", "uq_weekly_coach_messages_user_week"):
        op.drop_constraint(
            "uq_weekly_coach_messages_user_week",
            "weekly_coach_messages",
            type_="unique",
        )

    if not _constraint_exists("weekly_coach_messages", "uq_weekly_coach_messages_user_date"):
        op.create_unique_constraint(
            "uq_weekly_coach_messages_user_date",
            "weekly_coach_messages",
            ["user_id", "for_date"],
        )

    if not index_exists("weekly_coach_messages", "ix_weekly_coach_messages_user_for_date"):
        op.create_index(
            "ix_weekly_coach_messages_user_for_date",
            "weekly_coach_messages",
            ["user_id", "for_date"],
        )


def downgrade() -> None:
    if not table_exists("weekly_coach_messages"):
        return

    if index_exists("weekly_coach_messages", "ix_weekly_coach_messages_user_for_date"):
        op.drop_index(
            "ix_weekly_coach_messages_user_for_date",
            table_name="weekly_coach_messages",
        )

    if _constraint_exists("weekly_coach_messages", "uq_weekly_coach_messages_user_date"):
        op.drop_constraint(
            "uq_weekly_coach_messages_user_date",
            "weekly_coach_messages",
            type_="unique",
        )

    if column_exists("weekly_coach_messages", "for_date"):
        op.drop_column("weekly_coach_messages", "for_date")

    if not _constraint_exists("weekly_coach_messages", "uq_weekly_coach_messages_user_week"):
        op.create_unique_constraint(
            "uq_weekly_coach_messages_user_week",
            "weekly_coach_messages",
            ["user_id", "for_week"],
        )
