"""Add races_checkpoints and planned_load tables (issue #1099).

races_checkpoints stores named events (races or intermediate checkpoints) with
an optional goal time and distance. The `type` column is constrained to the
values 'race' or 'checkpoint' via a CHECK constraint.

planned_load stores one planned-TSS value per calendar date, used for
projection planning. The date column is the primary key so each date has
exactly one planned load value.

Revision ID: 017a12a2a6f5
Revises: 948fd1cacfd7
Create Date: 2026-06-29 19:51:23.442937
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

# revision identifiers, used by Alembic.
revision: str = "017a12a2a6f5"
down_revision: Union[str, None] = "948fd1cacfd7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("races_checkpoints"):
        op.create_table(
            "races_checkpoints",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
                primary_key=True,
            ),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("distance_km", sa.Numeric(precision=8, scale=3), nullable=True),
            sa.Column("type", sa.Text(), nullable=False),
            sa.Column("goal_time", sa.Integer(), nullable=True),
            sa.CheckConstraint("type IN ('race', 'checkpoint')", name="ck_races_checkpoints_type"),
        )

    if not table_exists("planned_load"):
        op.create_table(
            "planned_load",
            sa.Column("date", sa.Date(), primary_key=True),
            sa.Column("planned_tss", sa.Numeric(precision=8, scale=2), nullable=False),
        )


def downgrade() -> None:
    if table_exists("planned_load"):
        op.drop_table("planned_load")
    if table_exists("races_checkpoints"):
        op.drop_table("races_checkpoints")
