"""Add ctl_days and atl_days to training_load_snapshots (issue #1366).

Records which EWMA time constants produced each snapshot row so the
cache can be invalidated when the user accepts a new calibration.
NULL means the row was computed with the module defaults (CTL_DAYS=42,
ATL_DAYS=7).

Revision ID: 3c5bf7cf48ed
Revises: 24d017bf47ed
Create Date: 2026-07-13 11:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "3c5bf7cf48ed"
down_revision: Union[str, Sequence[str], None] = "24d017bf47ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("training_load_snapshots", "ctl_days"):
        op.add_column(
            "training_load_snapshots",
            sa.Column("ctl_days", sa.Integer(), nullable=True),
        )
    if not column_exists("training_load_snapshots", "atl_days"):
        op.add_column(
            "training_load_snapshots",
            sa.Column("atl_days", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("training_load_snapshots", "atl_days"):
        op.drop_column("training_load_snapshots", "atl_days")
    if column_exists("training_load_snapshots", "ctl_days"):
        op.drop_column("training_load_snapshots", "ctl_days")
