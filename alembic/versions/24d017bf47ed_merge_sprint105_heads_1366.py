"""merge sprint-105 heads before ctl_atl calibration loop (issue #1366)

Revision ID: 24d017bf47ed
Revises: 1da954a27351bb1b, a0o1p2q3r4s5, cea323ec2396, e4f5a6b7c8d9
Create Date: 2026-07-13 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "24d017bf47ed"
down_revision: Union[str, Sequence[str], None] = ("1da954a27351bb1b", "a0o1p2q3r4s5", "cea323ec2396", "e4f5a6b7c8d9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
