"""add acwr and formula_version to training_load_snapshots

Part of the CTL/ATL/TSB/ACWR single-source-of-truth fix: readiness cards and
the weekly coach report were independently computing these metrics and could
disagree for the same date. training_load_snapshots becomes the sole
producer; formula_version lets any row from before this consolidation (or a
future formula change) be detected and recomputed rather than silently
served stale. See docs/calculations/training-load.md.

Revision ID: a2f7ab0f10a1
Revises: f56d6c6ddbbb
Create Date: 2026-07-10 00:17:12.295480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'a2f7ab0f10a1'
down_revision: Union[str, Sequence[str], None] = 'f56d6c6ddbbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists("training_load_snapshots", "acwr"):
        op.add_column(
            "training_load_snapshots",
            sa.Column("acwr", sa.Float(), nullable=True),
        )
    if not column_exists("training_load_snapshots", "formula_version"):
        op.add_column(
            "training_load_snapshots",
            sa.Column("formula_version", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if column_exists("training_load_snapshots", "formula_version"):
        op.drop_column("training_load_snapshots", "formula_version")
    if column_exists("training_load_snapshots", "acwr"):
        op.drop_column("training_load_snapshots", "acwr")
