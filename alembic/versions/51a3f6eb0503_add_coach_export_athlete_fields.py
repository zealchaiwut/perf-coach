"""add_coach_export_athlete_fields

Revision ID: 51a3f6eb0503
Revises: c52d0c11f808
Create Date: 2026-07-30 17:55:47.176620

Adds the three ``users`` columns the coach export payload needs a source for:

- ``birth_date``           — ``athlete.age`` is derived from this; no other row held it.
- ``athlete_context``      — the single free-text identity field (identity lives in
                             the JSON, not the prompt template). Deliberately separate
                             from plan-prefs ``notes``, which are scheduling
                             instructions rather than who the athlete is.
- ``last_coach_export_at`` — stamps the previous export so the template's Season
                             check section can be skipped when nothing moved. One
                             column, no new table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '51a3f6eb0503'
down_revision: Union[str, Sequence[str], None] = 'c52d0c11f808'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("birth_date", lambda: sa.Column("birth_date", sa.Date(), nullable=True)),
    ("athlete_context", lambda: sa.Column("athlete_context", sa.Text(), nullable=True)),
    (
        "last_coach_export_at",
        lambda: sa.Column("last_coach_export_at", sa.DateTime(timezone=True), nullable=True),
    ),
)


def upgrade() -> None:
    """Add users.birth_date / athlete_context / last_coach_export_at."""
    if not table_exists("users"):
        return
    for name, column in _COLUMNS:
        if not column_exists("users", name):
            op.add_column("users", column())


def downgrade() -> None:
    """Drop the three coach-export athlete columns."""
    if not table_exists("users"):
        return
    for name, _ in reversed(_COLUMNS):
        if column_exists("users", name):
            op.drop_column("users", name)
