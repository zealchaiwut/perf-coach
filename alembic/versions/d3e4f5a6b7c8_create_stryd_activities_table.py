"""create stryd_activities cache table

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-30 00:00:00.000000

Expected form_metrics JSON shape:
  {
    "leg_spring_stiffness": 8.7,
    "ground_contact_time_ms": 235,
    "vertical_oscillation_cm": 7.2,
    "form_power_w": 32,
    "cadence_spm": 178
  }
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("stryd_activities"):
        op.create_table(
            "stryd_activities",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("stryd_activity_id", sa.String(255), nullable=False),
            sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("distance_km", sa.Numeric(10, 3), nullable=True),
            sa.Column("duration_seconds", sa.Integer, nullable=True),
            sa.Column("avg_power_w", sa.Integer, nullable=True),
            sa.Column("avg_hr", sa.Integer, nullable=True),
            sa.Column("tss", sa.Integer, nullable=True),
            sa.Column("form_metrics", postgresql.JSONB, nullable=True),
            sa.Column("power_zones", postgresql.JSONB, nullable=True),
            sa.Column("splits", postgresql.JSONB, nullable=True),
            sa.Column("raw_payload", postgresql.JSONB, nullable=False),
            sa.Column(
                "synced_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "stryd_activity_id",
                name="uq_stryd_activities_stryd_activity_id",
            ),
        )

    if not index_exists("stryd_activities", "ix_stryd_activities_stryd_activity_id"):
        op.create_index(
            "ix_stryd_activities_stryd_activity_id",
            "stryd_activities",
            ["stryd_activity_id"],
        )

    if not index_exists("stryd_activities", "ix_stryd_activities_start_time"):
        op.create_index(
            "ix_stryd_activities_start_time",
            "stryd_activities",
            ["start_time"],
        )

    if not index_exists("stryd_activities", "ix_stryd_activities_user_start_time"):
        op.create_index(
            "ix_stryd_activities_user_start_time",
            "stryd_activities",
            ["user_id", "start_time"],
        )


def downgrade() -> None:
    if not table_exists("stryd_activities"):
        return
    for idx in (
        "ix_stryd_activities_user_start_time",
        "ix_stryd_activities_start_time",
        "ix_stryd_activities_stryd_activity_id",
    ):
        if index_exists("stryd_activities", idx):
            op.drop_index(idx, table_name="stryd_activities")
    op.drop_table("stryd_activities")
