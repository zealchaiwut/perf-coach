"""Add source columns to user_preferences for threshold provenance tracking.

Each threshold column (ftp_w, threshold_hr, threshold_pace_seconds_per_km)
gets a paired *_source column recording whether the value came from a
'user_accepted' suggestion or was set manually ('manual' or NULL).

Revision ID: aa1b2c3d4e5f
Revises: z9n0o1p2q3r4
Create Date: 2026-06-18

"""
from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision = "aa1b2c3d4e5f"
down_revision = "z9n0o1p2q3r4"
branch_labels = None
depends_on = None


def upgrade():
    if not column_exists("user_preferences", "ftp_w_source"):
        op.add_column(
            "user_preferences",
            sa.Column("ftp_w_source", sa.String(30), nullable=True),
        )
    if not column_exists("user_preferences", "threshold_hr_source"):
        op.add_column(
            "user_preferences",
            sa.Column("threshold_hr_source", sa.String(30), nullable=True),
        )
    if not column_exists("user_preferences", "threshold_pace_seconds_per_km_source"):
        op.add_column(
            "user_preferences",
            sa.Column("threshold_pace_seconds_per_km_source", sa.String(30), nullable=True),
        )


def downgrade():
    if column_exists("user_preferences", "ftp_w_source"):
        op.drop_column("user_preferences", "ftp_w_source")
    if column_exists("user_preferences", "threshold_hr_source"):
        op.drop_column("user_preferences", "threshold_hr_source")
    if column_exists("user_preferences", "threshold_pace_seconds_per_km_source"):
        op.drop_column("user_preferences", "threshold_pace_seconds_per_km_source")
