"""race_roles_p6_4

Revision ID: 2f84f8c79884
Revises: c4b5ed9f6d24
Create Date: 2026-11-22 15:47:08.630750

Revamp P6-4 (#1878): role enum, role-specific targets, add-on workout link.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, index_exists

revision: str = "2f84f8c79884"
down_revision: Union[str, Sequence[str], None] = "c4b5ed9f6d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_VALUES = ("a_race", "pb", "long_run", "fun")


def upgrade() -> None:
    if not column_exists("races", "role"):
        op.add_column(
            "races",
            sa.Column("role", sa.String(20), nullable=False, server_default="pb"),
        )
    if not column_exists("races", "power_cap_w"):
        op.add_column("races", sa.Column("power_cap_w", sa.Integer(), nullable=True))
    if not column_exists("races", "addon_distance_km"):
        op.add_column("races", sa.Column("addon_distance_km", sa.Numeric(8, 3), nullable=True))
    if not column_exists("races", "goal_band_low_seconds"):
        op.add_column("races", sa.Column("goal_band_low_seconds", sa.Integer(), nullable=True))
    if not column_exists("races", "goal_band_high_seconds"):
        op.add_column("races", sa.Column("goal_band_high_seconds", sa.Integer(), nullable=True))
    if not column_exists("races", "addon_workout_id"):
        op.add_column(
            "races",
            sa.Column(
                "addon_workout_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("workouts.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not index_exists("races", "ix_races_addon_workout_id"):
        op.create_index("ix_races_addon_workout_id", "races", ["addon_workout_id"])

    op.execute(
        """
        UPDATE races SET role = CASE
            WHEN race_type = 'checkpoint' THEN 'long_run'
            WHEN priority = 'A' THEN 'a_race'
            WHEN priority = 'B' THEN 'pb'
            ELSE 'fun'
        END
        WHERE role = 'pb' OR role IS NULL
        """
    )


def downgrade() -> None:
    if index_exists("races", "ix_races_addon_workout_id"):
        op.drop_index("ix_races_addon_workout_id", table_name="races")
    for col in (
        "addon_workout_id",
        "goal_band_high_seconds",
        "goal_band_low_seconds",
        "addon_distance_km",
        "power_cap_w",
        "role",
    ):
        if column_exists("races", col):
            op.drop_column("races", col)