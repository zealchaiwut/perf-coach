"""add_scale_constant_max_tss_to_user_preferences

Revision ID: 1a199ee7593e
Revises: 63d019bb0d5b
Create Date: 2026-08-04 18:54:13.416638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '1a199ee7593e'
down_revision: Union[str, Sequence[str], None] = '63d019bb0d5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists("user_preferences", "scale_constant"):
        op.add_column(
            "user_preferences",
            sa.Column("scale_constant", sa.Float(), nullable=True),
        )
    if not column_exists("user_preferences", "max_tss"):
        op.add_column(
            "user_preferences",
            sa.Column("max_tss", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if column_exists("user_preferences", "max_tss"):
        op.drop_column("user_preferences", "max_tss")
    if column_exists("user_preferences", "scale_constant"):
        op.drop_column("user_preferences", "scale_constant")
