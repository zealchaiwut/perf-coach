"""merge_perf_score_history_and_ctl_atl_heads_1361

Revision ID: 516c211f31f0
Revises: 129d863fa625, 3c5bf7cf48ed
Create Date: 2026-07-13 16:30:19.960655

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '516c211f31f0'
down_revision: Union[str, Sequence[str], None] = ('129d863fa625', '3c5bf7cf48ed')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
