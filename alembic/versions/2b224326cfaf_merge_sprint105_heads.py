"""merge_sprint105_heads

Revision ID: 2b224326cfaf
Revises: bf3b956dd2e0, fe28c4815e7e
Create Date: 2026-07-13 10:10:48.086863

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b224326cfaf'
down_revision: Union[str, Sequence[str], None] = ('bf3b956dd2e0', 'fe28c4815e7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
