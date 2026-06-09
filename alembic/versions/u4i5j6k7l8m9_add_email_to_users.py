"""Add email column to users table.

Revision ID: u4i5j6k7l8m9
Revises: t3h4i5j6k7l8
Create Date: 2026-06-09

"""
from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision = "u4i5j6k7l8m9"
down_revision = "t3h4i5j6k7l8"
branch_labels = None
depends_on = None


def upgrade():
    if not column_exists("users", "email"):
        op.add_column("users", sa.Column("email", sa.String(255), nullable=True))


def downgrade():
    if column_exists("users", "email"):
        op.drop_column("users", "email")
