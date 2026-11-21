"""decisions_race_session_links

Revision ID: 040c0bcc655a
Revises: 8d8cd37743d3
Create Date: 2026-11-21 23:22:04.403278

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, index_exists


# revision identifiers, used by Alembic.
revision: str = '040c0bcc655a'
down_revision: Union[str, Sequence[str], None] = '8d8cd37743d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Link a decision to the race and/or session it came from (P4-13)."""
    if not column_exists("decisions", "race_id"):
        op.add_column(
            "decisions",
            sa.Column("race_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("races.id", ondelete="SET NULL"), nullable=True),
        )
    if not column_exists("decisions", "session_id"):
        op.add_column(
            "decisions",
            sa.Column("session_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("workouts.id", ondelete="SET NULL"), nullable=True),
        )
    if not index_exists("decisions", "ix_decisions_race_id"):
        op.create_index("ix_decisions_race_id", "decisions", ["race_id"])


def downgrade() -> None:
    if index_exists("decisions", "ix_decisions_race_id"):
        op.drop_index("ix_decisions_race_id", table_name="decisions")
    if column_exists("decisions", "session_id"):
        op.drop_column("decisions", "session_id")
    if column_exists("decisions", "race_id"):
        op.drop_column("decisions", "race_id")
