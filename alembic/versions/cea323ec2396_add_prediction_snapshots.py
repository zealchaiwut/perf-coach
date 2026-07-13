"""Add prediction_snapshots table for forecast-vs-actual tracking (issue #1362).

One row per user per day — stores the morning projection forecast so that
future accuracy analysis can compare predicted vs actual race performance.

Revision ID: cea323ec2396
Revises: 2b224326cfaf
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "cea323ec2396"
down_revision: Union[str, Sequence[str], None] = "2b224326cfaf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("prediction_snapshots"):
        return

    op.create_table(
        "prediction_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "snapshot_date", name="uq_prediction_snapshots_user_date"),
    )
    op.create_foreign_key(
        "prediction_snapshots_user_id_fkey",
        "prediction_snapshots",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    if not index_exists("prediction_snapshots", "ix_prediction_snapshots_user_date"):
        op.create_index(
            "ix_prediction_snapshots_user_date",
            "prediction_snapshots",
            ["user_id", "snapshot_date"],
        )


def downgrade() -> None:
    if not table_exists("prediction_snapshots"):
        return
    if index_exists("prediction_snapshots", "ix_prediction_snapshots_user_date"):
        op.drop_index("ix_prediction_snapshots_user_date", table_name="prediction_snapshots")
    op.drop_table("prediction_snapshots")
