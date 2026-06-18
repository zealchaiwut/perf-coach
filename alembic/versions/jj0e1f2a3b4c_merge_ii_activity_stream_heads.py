"""Merge the two ii9 sprint-63.1 heads before adding tss_method.

Both ii9d0e1f2a3b (add_detail_and_streams_payload_to_strava_activities) and
ii9d0e1f2g3h (add_channel_attribution_to_activity_streams) branched from
hh8c9d0e1f2g and were never reconciled, leaving the schema with two Alembic
heads. This is a no-op merge node that joins them back into a single head.

Revision ID: jj0e1f2a3b4c
Revises: ii9d0e1f2a3b, ii9d0e1f2g3h
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

revision: str = "jj0e1f2a3b4c"
down_revision: Union[str, tuple, None] = ("ii9d0e1f2a3b", "ii9d0e1f2g3h")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
