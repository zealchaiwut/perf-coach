"""Change stryd_credentials.athlete_id from BigInteger to String.

Stryd athlete ids are UUID strings (e.g. 49c13d2b-a883-…), not numeric like
Strava's. The int column made /api/stryd/connect crash after a successful Stryd
signin. Widen to String(64). Idempotent + safe (column is nullable, no numeric
data to lose).

Revision ID: cc3d4e5f6a7b
Revises: bb2c3d4e5f6a
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "cc3d4e5f6a7b"
down_revision: Union[str, None] = "bb2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if column_exists("stryd_credentials", "athlete_id"):
        op.alter_column(
            "stryd_credentials",
            "athlete_id",
            type_=sa.String(64),
            existing_nullable=True,
            postgresql_using="athlete_id::text",
        )


def downgrade() -> None:
    if column_exists("stryd_credentials", "athlete_id"):
        op.alter_column(
            "stryd_credentials",
            "athlete_id",
            type_=sa.BigInteger(),
            existing_nullable=True,
            postgresql_using="athlete_id::bigint",
        )
