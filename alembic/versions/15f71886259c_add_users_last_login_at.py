"""add users last_login_at

Revision ID: 15f71886259c
Revises: c6b1492e2cc5
Create Date: 2026-06-25 23:09:02.265714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '15f71886259c'
down_revision: Union[str, Sequence[str], None] = 'c6b1492e2cc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists("users", "last_login_at"):
        op.add_column(
            "users",
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if column_exists("users", "last_login_at"):
        op.drop_column("users", "last_login_at")
