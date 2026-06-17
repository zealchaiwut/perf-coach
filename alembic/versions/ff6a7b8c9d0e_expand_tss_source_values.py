"""Expand the tss_source check constraint to allow method-level sources.

tss.py reports the IF method (power/pace/hr/duration_only) and Stryd supplies
'stryd'. The old constraint only allowed manual/calculated, which blocked the
TSS-fallback wiring. Keep the legacy values too.

Revision ID: ff6a7b8c9d0e
Revises: ee5f6a7b8c9d
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ff6a7b8c9d0e"
down_revision: Union[str, None] = "ee5f6a7b8c9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED = "'manual', 'calculated', 'stryd', 'power', 'pace', 'hr', 'duration_only'"


def upgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_tss_source_values")
    op.execute(
        "ALTER TABLE workouts ADD CONSTRAINT ck_workouts_tss_source_values "
        f"CHECK (tss_source IS NULL OR tss_source IN ({_ALLOWED}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workouts DROP CONSTRAINT IF EXISTS ck_workouts_tss_source_values")
    op.execute(
        "ALTER TABLE workouts ADD CONSTRAINT ck_workouts_tss_source_values "
        "CHECK (tss_source IS NULL OR tss_source IN ('manual', 'calculated'))"
    )
