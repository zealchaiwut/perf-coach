"""merge daily_readiness branch heads into single head

Revision ID: b0c1d2e3f4a5
Revises: 59a1b2c3d4e5, a9b0c1d2e3f4
Create Date: 2026-05-28 00:00:00.000000

Merges the two parallel daily_readiness creation paths into a single head
so that alembic upgrade head works regardless of which branch path was
previously applied to the database.

Branch A: 38a0b1c2d3e4 → 59a1b2c3d4e5
Branch B: 38a0b1c2d3e4 → f6a7b8c9d0e1 → a9b0c1d2e3f4

Both 59a1b2c3d4e5 and a9b0c1d2e3f4 are idempotent (guarded with
has_table checks), so a DB on either path can safely traverse the other
branch's migration before arriving at this merge point.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = ("59a1b2c3d4e5", "a9b0c1d2e3f4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
