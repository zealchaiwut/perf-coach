"""merge_heads

Revision ID: bf525c2c1caa
Revises: bf3b956dd2e0, fe28c4815e7e
Create Date: 2026-07-13 09:47:43.163277

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = 'bf525c2c1caa'
down_revision: Union[str, Sequence[str], None] = ('bf3b956dd2e0', 'fe28c4815e7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
