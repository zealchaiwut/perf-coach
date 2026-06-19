"""add_strength_rpe_max_to_user_preferences

Revision ID: 8f9eee6bf79b
Revises: 046b014b2eab
Create Date: 2026-06-19 18:17:13.630101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f9eee6bf79b'
down_revision: Union[str, Sequence[str], None] = '046b014b2eab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user_preferences",
        sa.Column("strength_rpe_max", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_preferences", "strength_rpe_max")
