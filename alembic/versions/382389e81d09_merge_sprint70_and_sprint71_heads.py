"""merge_sprint70_and_sprint71_heads

Revision ID: 382389e81d09
Revises: 145b95d5baf0, d915ffcb4c0c
Create Date: 2026-06-19 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '382389e81d09'
down_revision: Union[str, Sequence[str], None] = ('145b95d5baf0', 'd915ffcb4c0c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
