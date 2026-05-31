"""Add training_load_snapshots table for caching CTL/ATL/TSB values.

Revision ID: k4e5f6a7b8c9
Revises: j3d4e5f6a7b8
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from helpers import table_exists, index_exists

revision = "k4e5f6a7b8c9"
down_revision = "j3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("training_load_snapshots"):
        return

    op.create_table(
        "training_load_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("tss_for_day", sa.Integer, nullable=False),
        sa.Column("ctl", sa.Float, nullable=False),
        sa.Column("atl", sa.Float, nullable=False),
        sa.Column("tsb", sa.Float, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "snapshot_date", name="uq_training_load_snapshots_user_date"),
    )

    if not index_exists("training_load_snapshots", "ix_training_load_snapshots_user_date"):
        op.create_index(
            "ix_training_load_snapshots_user_date",
            "training_load_snapshots",
            ["user_id", "snapshot_date"],
        )


def downgrade():
    op.drop_index("ix_training_load_snapshots_user_date", table_name="training_load_snapshots")
    op.drop_table("training_load_snapshots")
