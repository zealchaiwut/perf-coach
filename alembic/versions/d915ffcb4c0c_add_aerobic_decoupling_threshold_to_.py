"""add_aerobic_decoupling_threshold_to_user_preferences

Revision ID: d915ffcb4c0c
Revises: 8f9eee6bf79b
Create Date: 2026-06-19 18:35:42.325652

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd915ffcb4c0c'
down_revision: Union[str, Sequence[str], None] = '8f9eee6bf79b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user_preferences",
        sa.Column("aerobic_decoupling_threshold", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_preferences", "aerobic_decoupling_threshold")
