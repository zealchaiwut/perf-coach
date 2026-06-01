"""Add is_admin flag to users.

Marks privileged users. For now it gates the Users management page; real
authentication/credentials come later.

Revision ID: l5f6a7b8c9d0
Revises: m6a7b8c9d0e1
Create Date: 2026-06-01

"""
from alembic import op
import sqlalchemy as sa
from helpers import column_exists

revision = "l5f6a7b8c9d0"
down_revision = "m6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    if column_exists("users", "is_admin"):
        return
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    if not column_exists("users", "is_admin"):
        return
    op.drop_column("users", "is_admin")
