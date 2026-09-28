"""sprint136 mobility session_type patterns skipped

Revision ID: ee582be657e7
Revises: 40af4911ec93
Create Date: 2026-09-28

WC-10: mobility session_type + skipped status on planned_sessions
WC-11: plan_patterns.kind += mobility
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ee582be657e7"
down_revision: Union[str, Sequence[str], None] = "40af4911ec93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE plan_patterns DROP CONSTRAINT IF EXISTS ck_plan_patterns_kind")
    op.execute(
        "ALTER TABLE plan_patterns ADD CONSTRAINT ck_plan_patterns_kind "
        "CHECK (kind IN ('run', 'strength', 'mobility'))"
    )

    op.execute("ALTER TABLE planned_sessions DROP CONSTRAINT IF EXISTS ck_planned_sessions_session_type")
    op.execute(
        "ALTER TABLE planned_sessions ADD CONSTRAINT ck_planned_sessions_session_type "
        "CHECK (session_type IN ('run', 'strength', 'plyo', 'stretch', 'rest', 'mobility'))"
    )
    op.execute("ALTER TABLE planned_sessions DROP CONSTRAINT IF EXISTS ck_planned_sessions_status")
    op.execute(
        "ALTER TABLE planned_sessions ADD CONSTRAINT ck_planned_sessions_status "
        "CHECK (status IN ("
        "'planned', 'missed', 'missed_auto', 'missed_manual', "
        "'needs_review', 'done_auto', 'done_manual', 'skipped'"
        "))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE planned_sessions DROP CONSTRAINT IF EXISTS ck_planned_sessions_status")
    op.execute("ALTER TABLE planned_sessions DROP CONSTRAINT IF EXISTS ck_planned_sessions_session_type")
    op.execute("ALTER TABLE plan_patterns DROP CONSTRAINT IF EXISTS ck_plan_patterns_kind")
    op.execute(
        "ALTER TABLE plan_patterns ADD CONSTRAINT ck_plan_patterns_kind "
        "CHECK (kind IN ('run', 'strength'))"
    )
