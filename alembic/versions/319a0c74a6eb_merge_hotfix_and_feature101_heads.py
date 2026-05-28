"""merge hotfix and feature101 heads

Revision ID: 319a0c74a6eb
Revises: 6d756372aee1, b0c1d2e3f4a5
Create Date: 2026-05-28 19:52:22.463474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '319a0c74a6eb'
down_revision: Union[str, Sequence[str], None] = ('6d756372aee1', 'b0c1d2e3f4a5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
