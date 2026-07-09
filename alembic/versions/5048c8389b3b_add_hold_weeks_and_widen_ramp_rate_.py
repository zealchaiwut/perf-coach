"""add hold_weeks and widen ramp_rate precision

Part 1 of the race-anchored Plan tab revamp (Session Load Plan). Adds
training_plans.hold_weeks (peak-hold length in weeks, default 4) and widens
ramp_rate from Numeric(6,2) to Numeric(6,4) so it can hold a fractional
weekly rate like 0.055 (5.5%) rather than only two decimal places. Backfills
NULL/0 ramp_rate to 0.05 and NULL/0 taper_length to 3 — 0/0 is a legitimate
"maintain" setting but a terrible default, rendering a flat, broken-looking
season chart. See backend/services/load_plan.py and
docs/calculations/load-plan.md.

Revision ID: 5048c8389b3b
Revises: 458e1a9d8783
Create Date: 2026-07-09 19:13:06.760289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '5048c8389b3b'
down_revision: Union[str, Sequence[str], None] = '458e1a9d8783'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists("training_plans", "hold_weeks"):
        op.add_column(
            "training_plans",
            sa.Column("hold_weeks", sa.Integer(), server_default=sa.text("4"), nullable=False),
        )

    op.alter_column(
        "training_plans",
        "ramp_rate",
        type_=sa.Numeric(6, 4),
        existing_type=sa.Numeric(6, 2),
        existing_nullable=True,
    )

    op.execute(
        "UPDATE training_plans SET ramp_rate = 0.05 WHERE ramp_rate IS NULL OR ramp_rate = 0"
    )
    op.execute(
        "UPDATE training_plans SET taper_length = 3 WHERE taper_length IS NULL OR taper_length = 0"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "training_plans",
        "ramp_rate",
        type_=sa.Numeric(6, 2),
        existing_type=sa.Numeric(6, 4),
        existing_nullable=True,
    )
    if column_exists("training_plans", "hold_weeks"):
        op.drop_column("training_plans", "hold_weeks")
