"""planned_session plan_source

Revision ID: b72b310448b8
Revises: 4b2875119331
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "b72b310448b8"
down_revision: Union[str, Sequence[str], None] = "4b2875119331"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("planned_sessions", "plan_source"):
        op.add_column(
            "planned_sessions",
            sa.Column("plan_source", sa.String(20), nullable=False, server_default="user"),
        )
        op.execute(
            "UPDATE planned_sessions SET plan_source = 'coach' "
            "WHERE lower(session_type) = 'run' AND plan_source = 'user'"
        )


def downgrade() -> None:
    if column_exists("planned_sessions", "plan_source"):
        op.drop_column("planned_sessions", "plan_source")