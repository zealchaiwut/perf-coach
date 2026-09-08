"""Add api_tokens table for scoped read-only machine-caller tokens (issue #1759).

Tokens are stored as SHA-256 hex digests only; the plaintext is never persisted.
scope is constrained to 'read' for now; extend the check constraint when
write-scoped tokens are ever needed.

Revision ID: 0c4248ada3ed
Revises: b1be92b4c4ff
Create Date: 2026-09-07 12:33:18.885684
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "0c4248ada3ed"
down_revision: Union[str, Sequence[str], None] = "b1be92b4c4ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("api_tokens"):
        return
    op.create_table(
        "api_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "scope",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'read'"),
        ),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('read')", name="ck_api_tokens_scope_values"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index("ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    if not table_exists("api_tokens"):
        return
    op.drop_index("ix_api_tokens_token_hash", table_name="api_tokens")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_table("api_tokens")
