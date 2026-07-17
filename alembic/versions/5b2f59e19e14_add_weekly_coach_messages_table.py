"""add_weekly_coach_messages_table

Revision ID: 5b2f59e19e14
Revises: f5413962c763
Create Date: 2026-07-17 15:08:40.159057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = '5b2f59e19e14'
down_revision: Union[str, Sequence[str], None] = 'f5413962c763'
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
    if table_exists("weekly_coach_messages"):
        return

    op.create_table(
        "weekly_coach_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("for_week", sa.String(8), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("plan_state_snapshot", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "for_week",
            name="uq_weekly_coach_messages_user_week",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_weekly_coach_messages_user_generated_at",
        "weekly_coach_messages",
        ["user_id", "generated_at"],
    )


def downgrade() -> None:
    if not table_exists("weekly_coach_messages"):
        return

    if index_exists("weekly_coach_messages", "ix_weekly_coach_messages_user_generated_at"):
        op.drop_index(
            "ix_weekly_coach_messages_user_generated_at",
            table_name="weekly_coach_messages",
        )

    op.drop_table("weekly_coach_messages")
