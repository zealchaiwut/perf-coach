"""add_plyo_sessions_table

Revision ID: 6a4bc101eef3
Revises: e3f1c0da097c
Create Date: 2026-06-30 16:22:05.000669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

# revision identifiers, used by Alembic.
revision: str = '6a4bc101eef3'
down_revision: Union[str, Sequence[str], None] = '6de228e34220'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create plyo_sessions table (idempotent)."""
    if table_exists("plyo_sessions"):
        return

    op.create_table(
        "plyo_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("foot_contacts", sa.Integer(), nullable=False),
        sa.Column("plyo_phase", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
            name="plyo_sessions_user_id_fkey",
        ),
        sa.CheckConstraint(
            "foot_contacts >= 0",
            name="ck_plyo_sessions_foot_contacts_non_negative",
        ),
        sa.CheckConstraint(
            "plyo_phase IN ('intro', 'build', 'maintain')",
            name="ck_plyo_sessions_plyo_phase_values",
        ),
    )
    op.create_index(
        "ix_plyo_sessions_user_id_session_date",
        "plyo_sessions",
        ["user_id", "session_date"],
    )


def downgrade() -> None:
    """Drop plyo_sessions table."""
    if not table_exists("plyo_sessions"):
        return

    op.drop_index("ix_plyo_sessions_user_id_session_date", table_name="plyo_sessions")
    op.drop_table("plyo_sessions")
