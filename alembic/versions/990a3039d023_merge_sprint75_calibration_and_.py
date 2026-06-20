"""merge_sprint75_calibration_and_checkpoints_heads

Revision ID: 990a3039d023
Revises: 978bc203e81a, dd327d5ed495
Create Date: 2026-06-20 04:05:44.753220

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '990a3039d023'
down_revision: Union[str, Sequence[str], None] = ('978bc203e81a', 'dd327d5ed495')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
