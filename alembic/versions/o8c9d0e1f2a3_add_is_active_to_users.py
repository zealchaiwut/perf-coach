"""Add is_active column to users table.

Revision ID: o8c9d0e1f2a3
Revises: n7b8c9d0e1f2
Create Date: 2026-06-02

"""
from alembic import op
import sqlalchemy as sa
from helpers import column_exists

revision = "o8c9d0e1f2a3"
down_revision = "n7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    if not column_exists("users", "is_active"):
        op.add_column(
            "users",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )


def downgrade():
    if column_exists("users", "is_active"):
        op.drop_column("users", "is_active")
