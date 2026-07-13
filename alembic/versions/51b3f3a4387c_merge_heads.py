"""merge_heads

Revision ID: 51b3f3a4387c
Revises: bf3b956dd2e0, fe28c4815e7e
Create Date: 2026-07-13 15:31:41.435659

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51b3f3a4387c'
down_revision: Union[str, Sequence[str], None] = ('bf3b956dd2e0', 'fe28c4815e7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
