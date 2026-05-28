"""merge tss and readiness heads

Revision ID: 9588f70c15f5
Revises: 28535735d316, a9b0c1d2e3f4
Create Date: 2026-05-28 18:39:23.640346

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9588f70c15f5'
down_revision: Union[str, Sequence[str], None] = ('28535735d316', 'a9b0c1d2e3f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
