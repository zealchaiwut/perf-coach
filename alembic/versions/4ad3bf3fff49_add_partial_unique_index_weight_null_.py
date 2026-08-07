"""add_partial_unique_index_weight_null_time

Adds a partial unique index on weight_entries(user_id, entry_date)
WHERE entry_time IS NULL so the DB enforces at most one NULL-time entry
per user per date, and the PUT /api/weight-entries/by-date handler can
use an atomic INSERT ... ON CONFLICT DO UPDATE targeting this index
(issue #1210).

Revision ID: 4ad3bf3fff49
Revises: 1c4afa2ab696
Create Date: 2026-07-05 01:09:38.227873

"""
from typing import Sequence, Union

from alembic import op

from helpers import table_exists, index_exists


# revision identifiers, used by Alembic.
revision: str = '4ad3bf3fff49'
down_revision: Union[str, Sequence[str], None] = 'f31dde78c681'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "ix_weight_entries_user_date_null_time"


def upgrade() -> None:
    if not table_exists("weight_entries"):
        return
    if not index_exists("weight_entries", _INDEX_NAME):
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE UNIQUE INDEX CONCURRENTLY ix_weight_entries_user_date_null_time "
                "ON weight_entries (user_id, entry_date) "
                "WHERE entry_time IS NULL"
            )


def downgrade() -> None:
    if not table_exists("weight_entries"):
        return
    if index_exists("weight_entries", _INDEX_NAME):
        op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
