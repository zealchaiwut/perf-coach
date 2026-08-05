"""merge_heads

Revision ID: 7921872665c9
Revises: 25a16908c6b4, ad22fdb94551
Create Date: 2026-08-05 09:43:32.969635

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '7921872665c9'
down_revision: Union[str, Sequence[str], None] = ('25a16908c6b4', 'ad22fdb94551')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
