"""merge duplicate daily_readiness heads

Revision ID: 6d756372aee1
Revises: 9588f70c15f5
Create Date: 2026-05-28 18:44:07.904269

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d756372aee1'
down_revision: Union[str, Sequence[str], None] = '9588f70c15f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
