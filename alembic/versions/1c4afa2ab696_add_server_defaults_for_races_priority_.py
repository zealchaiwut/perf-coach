"""add_server_defaults_for_races_priority_and_status

Moves the 'A' and 'planned' defaults for races.priority and races.status
from application code into the DB schema so no caller-supplied default
lives in Python (issue #684). Idempotent: guards with column_exists.

Revision ID: 1c4afa2ab696
Revises: f32591c408cf
Create Date: 2026-07-04 17:54:04.218020

"""
from typing import Sequence, Union

from alembic import op

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '1c4afa2ab696'
down_revision: Union[str, Sequence[str], None] = 'f32591c408cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("races"):
        return
    if column_exists("races", "priority"):
        op.execute("ALTER TABLE races ALTER COLUMN priority SET DEFAULT 'A'")
    if column_exists("races", "status"):
        op.execute("ALTER TABLE races ALTER COLUMN status SET DEFAULT 'planned'")


def downgrade() -> None:
    if not table_exists("races"):
        return
    if column_exists("races", "priority"):
        op.execute("ALTER TABLE races ALTER COLUMN priority DROP DEFAULT")
    if column_exists("races", "status"):
        op.execute("ALTER TABLE races ALTER COLUMN status DROP DEFAULT")
