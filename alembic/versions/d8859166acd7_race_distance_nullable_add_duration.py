"""race_distance_nullable_add_duration

Revision ID: d8859166acd7
Revises: d16a76bf72ca
Create Date: 2026-07-02 00:45:30.137783

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'd8859166acd7'
down_revision: Union[str, Sequence[str], None] = 'd16a76bf72ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow duration-defined checkpoints (issue #1226): distance_km becomes
    nullable and a duration_seconds column is added. Idempotent."""
    op.execute("ALTER TABLE races ALTER COLUMN distance_km DROP NOT NULL")
    if not column_exists("races", "duration_seconds"):
        op.add_column("races", sa.Column("duration_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    if column_exists("races", "duration_seconds"):
        op.drop_column("races", "duration_seconds")
    # Note: distance_km NOT NULL is not restored (rows may now have NULL distance).
