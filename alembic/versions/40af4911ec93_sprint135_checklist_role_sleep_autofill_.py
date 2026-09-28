"""sprint135 checklist_role sleep autofill archive stretch

Revision ID: 40af4911ec93
Revises: 0c4248ada3ed
Create Date: 2026-09-28

WC-05: habits.checklist_role (core | optional | off)
WC-04: archive legacy coach.stretch_daily habits
WC-07: allow sleep.hours_min autofill source
"""
from typing import Sequence, Union

from alembic import op

revision: str = "40af4911ec93"
down_revision: Union[str, Sequence[str], None] = "0c4248ada3ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUTO_FILL_NEW = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km',"
    "'coach.stretch_daily','weight.logged','long_run.fuelled','sleep.hours_min')"
)
_AUTO_FILL_OLD = (
    "('workout.zone2_minutes','workout.run_count','workout.lift_count',"
    "'workout.total_duration_minutes','workout.distance_km',"
    "'coach.stretch_daily','weight.logged','long_run.fuelled')"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE habits ADD COLUMN IF NOT EXISTS checklist_role TEXT "
        "NOT NULL DEFAULT 'core'"
    )
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_checklist_role")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_checklist_role "
        "CHECK (checklist_role IN ('core', 'optional', 'off'))"
    )

    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_AUTO_FILL_NEW})"
    )

    # WC-04: retire legacy stretch habit rows (history preserved).
    op.execute(
        "UPDATE habits SET is_archived = true, archived_at = NOW(), active = false "
        "WHERE auto_fill_source = 'coach.stretch_daily' AND is_archived = false"
    )

    # Defaults from weekly-checklist item table.
    op.execute(
        "UPDATE habits SET checklist_role = 'optional' "
        "WHERE auto_fill_source = 'workout.zone2_minutes' AND checklist_role = 'core'"
    )
    op.execute(
        "UPDATE habits SET checklist_role = 'core' "
        "WHERE auto_fill_source IN ('weight.logged', 'long_run.fuelled') "
        "AND checklist_role = 'core'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE habits SET auto_fill_source = NULL "
        "WHERE auto_fill_source = 'sleep.hours_min'"
    )
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_auto_fill_source")
    op.execute(
        "ALTER TABLE habits ADD CONSTRAINT ck_habits_auto_fill_source "
        f"CHECK (auto_fill_source IS NULL OR auto_fill_source IN {_AUTO_FILL_OLD})"
    )
    op.execute("ALTER TABLE habits DROP CONSTRAINT IF EXISTS ck_habits_checklist_role")
    op.execute("ALTER TABLE habits DROP COLUMN IF EXISTS checklist_role")
