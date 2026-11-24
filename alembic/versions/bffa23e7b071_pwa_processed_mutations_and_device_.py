"""pwa_processed_mutations_and_device_sessions

Revision ID: bffa23e7b071
Revises: 167d5ceec13f
Create Date: 2026-11-24 15:03:50.066239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from helpers import table_exists

revision: str = "bffa23e7b071"
down_revision: Union[str, Sequence[str], None] = "167d5ceec13f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("processed_mutations"):
        op.create_table(
            "processed_mutations",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("client_mutation_id", UUID(as_uuid=True), nullable=False),
            sa.Column("op_type", sa.String(40), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("result", JSONB, nullable=True),
            sa.UniqueConstraint("user_id", "client_mutation_id", name="uq_processed_mutations_user_client"),
        )
        op.create_index("ix_processed_mutations_received_at", "processed_mutations", ["received_at"])
    if not table_exists("device_sessions"):
        op.create_table(
            "device_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("label", sa.String(100), nullable=True),
            sa.Column("csrf_current", sa.String(64), nullable=True),
            sa.Column("csrf_previous", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"])


def downgrade() -> None:
    if table_exists("device_sessions"):
        op.drop_table("device_sessions")
    if table_exists("processed_mutations"):
        op.drop_table("processed_mutations")
