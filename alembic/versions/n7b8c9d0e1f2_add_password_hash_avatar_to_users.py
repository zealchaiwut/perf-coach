"""Add password_hash, avatar, avatar_mime to users table.

Revision ID: n7b8c9d0e1f2
Revises: l5f6a7b8c9d0
Create Date: 2026-06-01

"""
from alembic import op
import sqlalchemy as sa
from helpers import column_exists

revision = "n7b8c9d0e1f2"
down_revision = "l5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    if not column_exists("users", "password_hash"):
        op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    if not column_exists("users", "avatar"):
        op.add_column("users", sa.Column("avatar", sa.LargeBinary(), nullable=True))
    if not column_exists("users", "avatar_mime"):
        op.add_column("users", sa.Column("avatar_mime", sa.Text(), nullable=True))


def downgrade():
    if column_exists("users", "avatar_mime"):
        op.drop_column("users", "avatar_mime")
    if column_exists("users", "avatar"):
        op.drop_column("users", "avatar")
    if column_exists("users", "password_hash"):
        op.drop_column("users", "password_hash")
