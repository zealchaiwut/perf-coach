"""merge_prefs_and_plan_drafts

Revision ID: 3e1c0945a812
Revises: 71b8f0d766c0, fbd9a848c17f
Create Date: 2026-07-20 14:56:12.804742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e1c0945a812'
down_revision: Union[str, Sequence[str], None] = ('71b8f0d766c0', 'fbd9a848c17f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
