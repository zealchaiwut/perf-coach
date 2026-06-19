"""merge races and height/duration-curve heads

Revision ID: mm3a4b5c6d7e
Revises: ll2a3b4c5d6e, ll2g3h4i5j6k
Create Date: 2026-06-19 10:26:23.723376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'mm3a4b5c6d7e'
down_revision: Union[str, Sequence[str], None] = ('ll2a3b4c5d6e', 'll2g3h4i5j6k')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
