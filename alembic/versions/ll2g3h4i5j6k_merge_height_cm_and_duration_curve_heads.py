"""Merge aa1b2c3d4e5g (height_cm) and kk1f2a3b4c5d (athlete-duration-curve) heads.

After feature/589 is merged, two heads exist in the alembic graph:
- aa1b2c3d4e5g: add_height_cm_to_users (child of a0o1p2q3r4s5)
- kk1f2a3b4c5d: add_athlete_duration_curves_table (child of jj0e1f2a3b4c)

This no-op merge node joins them so that alembic upgrade head works cleanly.

Revision ID: ll2g3h4i5j6k
Revises: aa1b2c3d4e5g, kk1f2a3b4c5d
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

revision: str = "ll2g3h4i5j6k"
down_revision: Union[str, tuple] = ("aa1b2c3d4e5g", "kk1f2a3b4c5d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    pass


def downgrade():
    pass
