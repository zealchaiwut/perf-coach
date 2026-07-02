"""merge_3_heads_for_1099

Revision ID: 948fd1cacfd7
Revises: 29e98a530414, 669f2c097cfa, 95da7162ead8
Create Date: 2026-06-29 19:51:20.289939

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '948fd1cacfd7'
down_revision: Union[str, Sequence[str], None] = ('29e98a530414', '669f2c097cfa', '95da7162ead8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
