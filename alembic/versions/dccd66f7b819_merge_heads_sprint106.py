"""merge_heads_sprint106

Revision ID: dccd66f7b819
Revises: 3bd978fbbf19, a4cf1cbd5020, e7f0627cf5c9
Create Date: 2026-07-13 22:21:12.212577

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dccd66f7b819'
down_revision: Union[str, Sequence[str], None] = ('3bd978fbbf19', 'a4cf1cbd5020', 'e7f0627cf5c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
