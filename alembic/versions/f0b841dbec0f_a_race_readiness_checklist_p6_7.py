"""a_race_readiness_checklist_p6_7

Revision ID: f0b841dbec0f
Revises: 2f84f8c79884
Create Date: 2026-11-22

Revamp P6-7 (#1881): A-race toilet-plan notes and fuel columns for the checklist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "f0b841dbec0f"
down_revision: Union[str, Sequence[str], None] = "2f84f8c79884"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("races", "notes"):
        op.add_column("races", sa.Column("notes", sa.Text(), nullable=True))
    if not column_exists("races", "toilet_plan_done"):
        op.add_column(
            "races",
            sa.Column("toilet_plan_done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    if not column_exists("workouts", "gel_count"):
        op.add_column("workouts", sa.Column("gel_count", sa.Integer(), nullable=True))
    if not column_exists("workouts", "fluid_level"):
        op.add_column("workouts", sa.Column("fluid_level", sa.String(length=10), nullable=True))


def downgrade() -> None:
    if column_exists("workouts", "fluid_level"):
        op.drop_column("workouts", "fluid_level")
    if column_exists("workouts", "gel_count"):
        op.drop_column("workouts", "gel_count")
    if column_exists("races", "toilet_plan_done"):
        op.drop_column("races", "toilet_plan_done")
    if column_exists("races", "notes"):
        op.drop_column("races", "notes")