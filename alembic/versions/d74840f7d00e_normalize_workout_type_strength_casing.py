"""normalize_workout_type_strength_casing

Revision ID: d74840f7d00e
Revises: 8d14fe27be6b
Create Date: 2026-07-15 14:47:17.664075

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd74840f7d00e'
down_revision: Union[str, Sequence[str], None] = '8d14fe27be6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Collapse strength workout_type casing variants to canonical lowercase 'strength'.

    The manual-entry API path (backend/main.py's _normalize_workout_type)
    previously passed non-run types through verbatim, so strength sessions
    entered by hand could be stored as 'Strength' alongside the dominant
    lowercase 'strength' written by the Strava-sync path. Case-sensitive
    `workout_type = 'strength'` queries (structural_dose.py, consumed by the
    gap-analysis strength_lapsed rule, issue #1369) silently excluded those
    rows, producing false "no recent strength" advisories. Idempotent: safe
    to re-run.
    """
    op.execute(
        "UPDATE workouts SET workout_type = 'strength' "
        "WHERE lower(workout_type) = 'strength' "
        "AND workout_type <> 'strength'"
    )


def downgrade() -> None:
    """No-op: original per-row casing is not recoverable."""
    pass
