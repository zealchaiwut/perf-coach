"""merge sprint-69 and threshold-repair heads

Revision ID: 046b014b2eab
Revises: 6b72b2735b17, nn4d5e6f7g8h
Create Date: 2026-06-19 14:59:50.475869

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '046b014b2eab'
down_revision: Union[str, Sequence[str], None] = ('6b72b2735b17', 'nn4d5e6f7g8h')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
