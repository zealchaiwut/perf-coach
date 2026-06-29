"""Add training_plans table with ramp and taper parameters (issue #1101).

training_plans stores per-user training plan configuration including ramp_rate,
taper_start, taper_length, and taper_shape fields. All ramp/taper fields are
nullable to support plans created without these parameters.

Revision ID: 3f9e1b2c4a7d
Revises: 017a12a2a6f5
Create Date: 2026-06-29 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "3f9e1b2c4a7d"
down_revision: Union[str, None] = "017a12a2a6f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("training_plans"):
        op.create_table(
            "training_plans",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("ramp_rate", sa.Numeric(6, 2), nullable=True),
            sa.Column("taper_start", sa.Numeric(6, 2), nullable=True),
            sa.Column("taper_length", sa.Numeric(6, 2), nullable=True),
            sa.Column("taper_shape", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="training_plans_user_id_fkey",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="training_plans_pkey"),
            sa.CheckConstraint(
                "taper_shape IS NULL OR taper_shape IN ('linear', 'step', 'exponential')",
                name="ck_training_plans_taper_shape",
            ),
        )

    if not index_exists("training_plans", "ix_training_plans_user_id"):
        op.create_index(
            "ix_training_plans_user_id",
            "training_plans",
            ["user_id"],
        )


def downgrade() -> None:
    if table_exists("training_plans"):
        if index_exists("training_plans", "ix_training_plans_user_id"):
            op.drop_index("ix_training_plans_user_id", table_name="training_plans")
        op.drop_table("training_plans")
