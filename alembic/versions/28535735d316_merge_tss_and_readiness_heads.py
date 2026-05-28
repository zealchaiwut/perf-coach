"""merge tss and readiness heads

Revision ID: 28535735d316
Revises: f6a7b8c9d0e1, 59a1b2c3d4e5
Create Date: 2026-05-27 21:34:00.915877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28535735d316'
down_revision: Union[str, Sequence[str], None] = ('f6a7b8c9d0e1', '59a1b2c3d4e5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
