"""add_drive_sleep_connections_table

Stores Google Drive read-only OAuth connections for Health Sync sleep CSV imports.

Revision ID: 3f8a2b1c9d4e
Revises: 53b033936666
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "3f8a2b1c9d4e"
down_revision: Union[str, Sequence[str], None] = "53b033936666"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("drive_sleep_connections"):
        op.create_table(
            "drive_sleep_connections",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
            sa.Column("folder_id", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'not_connected'"),
            ),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.UniqueConstraint("user_id", name="uq_drive_sleep_connections_user_id"),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="drive_sleep_connections_user_id_fkey",
                ondelete="CASCADE",
            ),
        )


def downgrade() -> None:
    if table_exists("drive_sleep_connections"):
        op.drop_table("drive_sleep_connections")
