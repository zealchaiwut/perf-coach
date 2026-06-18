"""Merge the two ii9 activity-streams heads into a single head.

ii9d0e1f2a3b (add_detail_and_streams_payload_to_strava_activities) and
ii9d0e1f2g3h (add_channel_attribution_to_activity_streams) both branch from
hh8c9d0e1f2g and were never reconciled. This no-op merge node joins them so
that alembic upgrade head works cleanly.

Revision ID: jj0e1f2a3b4c
Revises: ii9d0e1f2a3b, ii9d0e1f2g3h
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

revision: str = "jj0e1f2a3b4c"
down_revision: Union[str, tuple] = ("ii9d0e1f2a3b", "ii9d0e1f2g3h")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    pass


def downgrade():
    pass
