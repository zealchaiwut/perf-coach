"""merge multiple heads from out-of-sync UAT database

Revision ID: 29e98a530414
Revises: 6b7db3c38f43
Create Date: 2026-06-27 14:40:01.368604

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29e98a530414'
down_revision: Union[str, Sequence[str], None] = '6b7db3c38f43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
