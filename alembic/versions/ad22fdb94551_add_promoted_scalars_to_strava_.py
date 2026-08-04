"""add_promoted_scalars_to_strava_activities

Revision ID: ad22fdb94551
Revises: 1a199ee7593e
Create Date: 2026-08-04 21:47:49.139118

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'ad22fdb94551'
down_revision: Union[str, Sequence[str], None] = '1a199ee7593e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add promoted scalar columns to strava_activities (issue #1307)."""
    if not column_exists("strava_activities", "laps"):
        op.add_column("strava_activities", sa.Column("laps", JSONB, nullable=True))
    if not column_exists("strava_activities", "splits_metric"):
        op.add_column("strava_activities", sa.Column("splits_metric", JSONB, nullable=True))
    if not column_exists("strava_activities", "best_efforts"):
        op.add_column("strava_activities", sa.Column("best_efforts", JSONB, nullable=True))
    if not column_exists("strava_activities", "calories"):
        op.add_column("strava_activities", sa.Column("calories", sa.Integer, nullable=True))


def downgrade() -> None:
    """Remove promoted scalar columns from strava_activities."""
    if column_exists("strava_activities", "calories"):
        op.drop_column("strava_activities", "calories")
    if column_exists("strava_activities", "best_efforts"):
        op.drop_column("strava_activities", "best_efforts")
    if column_exists("strava_activities", "splits_metric"):
        op.drop_column("strava_activities", "splits_metric")
    if column_exists("strava_activities", "laps"):
        op.drop_column("strava_activities", "laps")
