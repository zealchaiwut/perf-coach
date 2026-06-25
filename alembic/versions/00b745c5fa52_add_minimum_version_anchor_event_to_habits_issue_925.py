"""Add minimum_version and anchor_event to habits table (issue #925).

Additive, nullable columns for focus-aware coaching.
minimum_version: optional minimum viable version of the habit for struggling days.
anchor_event: optional existing action to pair the habit with.

Revision ID: 00b745c5fa52
Revises: z9n0o1p2q3r4
Create Date: 2026-06-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "00b745c5fa52"
down_revision: Union[str, None] = "z9n0o1p2q3r4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("habits", "minimum_version"):
        op.add_column(
            "habits",
            sa.Column("minimum_version", sa.Text(), nullable=True),
        )
    if not column_exists("habits", "anchor_event"):
        op.add_column(
            "habits",
            sa.Column("anchor_event", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("habits", "anchor_event"):
        op.drop_column("habits", "anchor_event")
    if column_exists("habits", "minimum_version"):
        op.drop_column("habits", "minimum_version")
