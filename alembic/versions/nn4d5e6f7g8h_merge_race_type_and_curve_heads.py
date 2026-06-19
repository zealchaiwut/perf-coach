"""Merge race_type branch and existing merge head into single head.

Revision ID: nn4d5e6f7g8h
Revises: ll2g3h4i5j6k, mm3c4d5e6f7g
Create Date: 2026-06-19 00:01:00.000000
"""
from typing import Sequence, Union

revision: str = "nn4d5e6f7g8h"
down_revision: Union[str, tuple] = ("ll2g3h4i5j6k", "mm3c4d5e6f7g")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
