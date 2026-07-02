"""normalize_workout_type_run_casing

Revision ID: d16a76bf72ca
Revises: 5552a8d45c57
Create Date: 2026-07-01 22:49:40.515802

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd16a76bf72ca'
down_revision: Union[str, Sequence[str], None] = '5552a8d45c57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Collapse run workout_type casing variants to canonical lowercase 'run'.

    Runs were stored inconsistently as 'run' (dominant), 'Run', and 'Running',
    which broke run-scoped queries that matched exactly (scoring, guardrail).
    Idempotent: safe to re-run.
    """
    op.execute(
        "UPDATE workouts SET workout_type = 'run' "
        "WHERE lower(workout_type) IN ('run', 'running') "
        "AND workout_type <> 'run'"
    )


def downgrade() -> None:
    """No-op: original per-row casing is not recoverable."""
    pass
