"""merge_p6_ladder_and_fuel_heads

Revision ID: 4c9d83c51eaf
Revises: 02d0f3df6d96, bb886c22e15f
Create Date: 2026-11-22 16:19:57.314154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c9d83c51eaf'
down_revision: Union[str, Sequence[str], None] = ('02d0f3df6d96', 'bb886c22e15f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
