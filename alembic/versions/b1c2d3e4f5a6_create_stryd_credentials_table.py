"""create stryd_credentials table

Security model: passwords are encrypted at the application layer using Fernet
symmetric encryption (cryptography library). A single key stored in the
STRYD_FERNET_KEY environment variable encrypts all users' passwords. This is a
practical shortcut for a single-user deployment — for multi-user hardening,
derive per-user keys from a master key + user-specific salt so that a leaked
ciphertext for one user cannot be decrypted without the master key AND that
user's salt.

Revision ID: b1c2d3e4f5a6
Revises: a8b9c0d1e2f3
Create Date: 2026-05-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("stryd_credentials"):
        return

    op.create_table(
        "stryd_credentials",
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
            unique=True,
        ),
        sa.Column("stryd_email", sa.String(255), nullable=False),
        sa.Column("stryd_password_encrypted", sa.Text, nullable=False),
        sa.Column("session_token", sa.Text, nullable=True),
        sa.Column("session_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("athlete_id", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    if not table_exists("stryd_credentials"):
        return
    op.drop_table("stryd_credentials")
