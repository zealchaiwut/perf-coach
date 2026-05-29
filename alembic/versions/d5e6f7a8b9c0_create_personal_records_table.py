"""create personal_records table

Revision ID: d5e6f7a8b9c0
Revises: c1d2e3f4a5b6
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("personal_records"):
        return

    op.create_table(
        "personal_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("track_key", sa.String(100), nullable=False),
        sa.Column("track_name", sa.String(200), nullable=False),
        sa.Column("track_type", sa.String(10), nullable=False),
        sa.Column("value_numeric", sa.Numeric(12, 4), nullable=False),
        sa.Column("achieved_on", sa.Date, nullable=False),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "track_type IN ('time', 'weight')",
            name="ck_personal_records_track_type",
        ),
        sa.CheckConstraint(
            "value_numeric > 0",
            name="ck_personal_records_value_positive",
        ),
    )


def downgrade() -> None:
    op.drop_table("personal_records")
