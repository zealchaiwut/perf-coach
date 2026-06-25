"""Add app_config table for persistent key-value server settings.

Revision ID: p9d0e1f2a3b4
Revises: o8c9d0e1f2a3
Create Date: 2026-06-02

"""
from alembic import op
import sqlalchemy as sa
from helpers import table_exists

revision = "p9d0e1f2a3b4"
down_revision = "o8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    if not table_exists("app_config"):
        op.create_table(
            "app_config",
            sa.Column("key", sa.String(100), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )


def downgrade():
    if table_exists("app_config"):
        op.drop_table("app_config")
