"""add_body_fat_pct_to_weight_entries

Revision ID: c76739716276
Revises: 1fff1ada408b
Create Date: 2026-07-30 22:51:16.195214

Optional weekly bioimpedance reading alongside the weigh-in. Bioimpedance is
poor at absolute body fat (±5 points) but acceptable at DIRECTION under
standardized conditions, and direction is the only thing asked of it: answering
what weight alone cannot — fat or lean mass?

Lean mass is derived (weight × (1 − bf/100)) rather than stored, so the two can
never disagree. Stored on ``weight_entries`` rather than a new table because a
composition reading IS a weigh-in with one extra number.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = 'c76739716276'
down_revision: Union[str, Sequence[str], None] = '1fff1ada408b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CK = "ck_weight_entries_body_fat_pct_range"


def upgrade() -> None:
    """Add weight_entries.body_fat_pct (nullable, 3-70%)."""
    if not table_exists("weight_entries"):
        return
    if not column_exists("weight_entries", "body_fat_pct"):
        op.add_column(
            "weight_entries",
            sa.Column("body_fat_pct", sa.Numeric(4, 1), nullable=True),
        )
    # Range guard: a bioimpedance scale that reports 2% or 90% is malfunctioning,
    # and a bad reading poisons a 4-week trend for a month.
    op.execute(f"ALTER TABLE weight_entries DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE weight_entries ADD CONSTRAINT {_CK} "
        "CHECK (body_fat_pct IS NULL OR (body_fat_pct >= 3 AND body_fat_pct <= 70))"
    )


def downgrade() -> None:
    """Drop weight_entries.body_fat_pct."""
    if not table_exists("weight_entries"):
        return
    op.execute(f"ALTER TABLE weight_entries DROP CONSTRAINT IF EXISTS {_CK}")
    if column_exists("weight_entries", "body_fat_pct"):
        op.drop_column("weight_entries", "body_fat_pct")
