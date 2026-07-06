"""merge_heads_sprint101

Revision ID: c7750b0bd23f
Revises: 4753105d42ae, a7812835b558
Create Date: 2026-07-06 18:50:53.731038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7750b0bd23f'
down_revision: Union[str, Sequence[str], None] = ('4753105d42ae', 'a7812835b558')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
