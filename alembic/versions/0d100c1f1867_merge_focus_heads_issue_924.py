"""merge_focus_heads_issue_924

Revision ID: 0d100c1f1867
Revises: 00b745c5fa52
Create Date: 2026-06-25 20:33:54.765954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d100c1f1867'
down_revision: Union[str, Sequence[str], None] = '00b745c5fa52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
