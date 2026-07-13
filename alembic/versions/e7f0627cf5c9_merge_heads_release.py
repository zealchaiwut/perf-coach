"""merge_heads_release

Revision ID: e7f0627cf5c9
Revises: 1d5caaeaaa26, 3e7f9a2c1d05, 516c211f31f0, da7cbe58ec60
Create Date: 2026-07-13 20:04:47.937082

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f0627cf5c9'
down_revision: Union[str, Sequence[str], None] = ('1d5caaeaaa26', '3e7f9a2c1d05', '516c211f31f0', 'da7cbe58ec60')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
