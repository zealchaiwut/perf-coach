"""create strava_activities cache table

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("strava_activities"):
        op.create_table(
            "strava_activities",
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
            sa.Column("strava_activity_id", sa.BigInteger, nullable=False),
            sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("activity_type", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("distance_km", sa.Numeric(10, 3), nullable=True),
            sa.Column("duration_seconds", sa.Integer, nullable=True),
            sa.Column("avg_hr", sa.Integer, nullable=True),
            sa.Column("max_hr", sa.Integer, nullable=True),
            sa.Column("elevation_m", sa.Integer, nullable=True),
            sa.Column("avg_power_w", sa.Integer, nullable=True),
            sa.Column("max_power_w", sa.Integer, nullable=True),
            sa.Column("device_name", sa.String(255), nullable=True),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column(
                "is_stryd_synced",
                sa.Boolean,
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.Column("raw_payload", postgresql.JSONB, nullable=False),
            sa.Column(
                "synced_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "strava_activity_id",
                name="uq_strava_activities_strava_activity_id",
            ),
        )

    if not index_exists("strava_activities", "ix_strava_activities_strava_activity_id"):
        op.create_index(
            "ix_strava_activities_strava_activity_id",
            "strava_activities",
            ["strava_activity_id"],
        )

    if not index_exists("strava_activities", "ix_strava_activities_start_time"):
        op.create_index(
            "ix_strava_activities_start_time",
            "strava_activities",
            ["start_time"],
        )

    if not index_exists("strava_activities", "ix_strava_activities_user_start_time"):
        op.create_index(
            "ix_strava_activities_user_start_time",
            "strava_activities",
            ["user_id", "start_time"],
        )


def downgrade() -> None:
    if not table_exists("strava_activities"):
        return
    for idx in (
        "ix_strava_activities_user_start_time",
        "ix_strava_activities_start_time",
        "ix_strava_activities_strava_activity_id",
    ):
        if index_exists("strava_activities", idx):
            op.drop_index(idx, table_name="strava_activities")
    op.drop_table("strava_activities")
