"""add google_oauth_credentials table

Revision ID: g0a1b2c3d4e5
Revises: f7a8b9c0d1e2
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

from helpers import table_exists

revision = "g0a1b2c3d4e5"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    # table_exists() (alembic/helpers.py) is this project's documented
    # idempotency-check convention (CLAUDE.md); this migration originally used
    # a one-off raw information_schema query instead, which worked but was
    # inconsistent with every other migration and unrecognized by the
    # idempotency test suite (#1606).
    if table_exists("google_oauth_credentials"):
        return

    op.create_table(
        "google_oauth_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("google_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id_token_payload", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade():
    if not table_exists("google_oauth_credentials"):
        return
    op.drop_table("google_oauth_credentials")
