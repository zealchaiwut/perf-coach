"""Add athlete_duration_curves table for per-athlete best-effort duration curve.

Stores one row per athlete containing the best power value for each duration
window across all processed run workouts. The curve_data JSONB column maps
str(duration_seconds) to {best_value, workout_id, date, confidence}.

Revision ID: kk1f2a3b4c5d
Revises: jj0e1f2a3b4c
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

from helpers import table_exists

revision: str = "kk1f2a3b4c5d"
down_revision: Union[str, None] = "jj0e1f2a3b4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    if not table_exists("athlete_duration_curves"):
        op.create_table(
            "athlete_duration_curves",
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "curve_data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )


def downgrade():
    if table_exists("athlete_duration_curves"):
        op.drop_table("athlete_duration_curves")
