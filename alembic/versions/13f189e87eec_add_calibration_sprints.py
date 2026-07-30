"""add_calibration_sprints

Revision ID: 13f189e87eec
Revises: 37e30b89c6cd
Create Date: 2026-07-30 23:45:14.332299

A calibration sprint is a bounded MEASUREMENT WEEK, never a diet: 5-7 days of
deliberate logging, once a month, with a visible end date from the moment it
starts. The end date is stored rather than derived so the countdown can never
quietly extend itself — an open-ended "just track for a while" is the thing that
turns into another failed attempt.

Its output is a maintenance recalibration, which is why it exists at all: five
days of real intake data beats a formula estimate, and the athlete only has to
do it twelve times a year.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import index_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '13f189e87eec'
down_revision: Union[str, Sequence[str], None] = '37e30b89c6cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the calibration_sprints table."""
    if not table_exists("calibration_sprints"):
        op.create_table(
            "calibration_sprints",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), server_default=sa.text("'active'"), nullable=False),
            sa.Column("logged_days", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("result_base_kcal", sa.Integer(), nullable=True),
            sa.Column("result_note", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "status IN ('active', 'completed', 'abandoned')",
                name="ck_calibration_sprints_status",
            ),
            sa.CheckConstraint(
                "end_date >= start_date", name="ck_calibration_sprints_dates"
            ),
        )

    if table_exists("calibration_sprints") and not index_exists(
        "calibration_sprints", "ix_calibration_sprints_user_start"
    ):
        op.create_index(
            "ix_calibration_sprints_user_start",
            "calibration_sprints",
            ["user_id", sa.text("start_date DESC")],
        )


def downgrade() -> None:
    """Drop the calibration_sprints table."""
    if table_exists("calibration_sprints"):
        if index_exists("calibration_sprints", "ix_calibration_sprints_user_start"):
            op.drop_index(
                "ix_calibration_sprints_user_start", table_name="calibration_sprints"
            )
        op.drop_table("calibration_sprints")
