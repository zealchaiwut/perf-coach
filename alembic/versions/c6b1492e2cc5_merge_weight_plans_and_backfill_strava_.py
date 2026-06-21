"""merge_weight_plans_and_backfill_strava_type

Revision ID: c6b1492e2cc5
Revises: 64d8ad2d9a42, 7723c7298d4d
Create Date: 2026-06-21 20:04:29.920322

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6b1492e2cc5'
down_revision: Union[str, Sequence[str], None] = ('64d8ad2d9a42', '7723c7298d4d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
