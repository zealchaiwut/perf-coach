"""add_race_calibrations_and_race_predictions

Revision ID: 8b73d5c83348
Revises: d4009bf7086a
Create Date: 2026-07-10 12:56:36.427670

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = '8b73d5c83348'
down_revision: Union[str, Sequence[str], None] = 'd4009bf7086a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create race_calibrations and race_predictions tables (idempotent)."""
    if not table_exists("race_calibrations"):
        op.create_table(
            "race_calibrations",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("race_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("race_date", sa.Date(), nullable=False),
            sa.Column("distance_km", sa.Numeric(8, 3), nullable=False),
            sa.Column("predicted_seconds", sa.Integer(), nullable=False),
            sa.Column("actual_seconds", sa.Integer(), nullable=False),
            sa.Column("correction", sa.Numeric(6, 4), nullable=False),
            sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'backcast'")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], ondelete="CASCADE", name="race_calibrations_user_id_fkey",
            ),
            sa.ForeignKeyConstraint(
                ["race_id"], ["races.id"], ondelete="CASCADE", name="race_calibrations_race_id_fkey",
            ),
            sa.UniqueConstraint("race_id", name="uq_race_calibrations_race_id"),
            sa.CheckConstraint("predicted_seconds > 0", name="ck_race_calibrations_predicted_seconds"),
            sa.CheckConstraint("actual_seconds > 0", name="ck_race_calibrations_actual_seconds"),
            sa.CheckConstraint("correction > 0", name="ck_race_calibrations_correction"),
            sa.CheckConstraint(
                "source IN ('backcast', 'stored_prediction')", name="ck_race_calibrations_source",
            ),
        )
        op.create_index(
            "ix_race_calibrations_user_date", "race_calibrations", ["user_id", "race_date"],
        )

    if not table_exists("race_predictions"):
        op.create_table(
            "race_predictions",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("race_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prediction_date", sa.Date(), nullable=False),
            sa.Column("predicted_seconds", sa.Integer(), nullable=False),
            sa.Column("band_seconds", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], ondelete="CASCADE", name="race_predictions_user_id_fkey",
            ),
            sa.ForeignKeyConstraint(
                ["race_id"], ["races.id"], ondelete="CASCADE", name="race_predictions_race_id_fkey",
            ),
            sa.UniqueConstraint("race_id", "prediction_date", name="uq_race_predictions_race_day"),
            sa.CheckConstraint("predicted_seconds > 0", name="ck_race_predictions_predicted_seconds"),
        )
        op.create_index(
            "ix_race_predictions_user_race", "race_predictions", ["user_id", "race_id"],
        )


def downgrade() -> None:
    """Drop race_predictions and race_calibrations tables."""
    if table_exists("race_predictions"):
        op.drop_index("ix_race_predictions_user_race", table_name="race_predictions")
        op.drop_table("race_predictions")
    if table_exists("race_calibrations"):
        op.drop_index("ix_race_calibrations_user_date", table_name="race_calibrations")
        op.drop_table("race_calibrations")
