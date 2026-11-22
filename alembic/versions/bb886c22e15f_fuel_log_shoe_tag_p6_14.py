"""fuel_log_shoe_tag_p6_14

Revision ID: bb886c22e15f
Revises: 482fc3199b4e
Create Date: 2026-11-22

Revamp P6-14 (#1888): athlete shoes and run fuel fields.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "bb886c22e15f"
down_revision: Union[str, Sequence[str], None] = "482fc3199b4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("athlete_shoes"):
        op.create_table(
            "athlete_shoes",
            sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("is_race_shoe", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("retired", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("total_km", sa.Numeric(precision=10, scale=2), server_default=sa.text("0"), nullable=False),
            sa.Column("longest_run_km", sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_athlete_shoes_user", "athlete_shoes", ["user_id"])
    if not column_exists("workouts", "shoe_id"):
        op.add_column("workouts", sa.Column("shoe_id", sa.UUID(), nullable=True))
        op.create_foreign_key("fk_workouts_shoe_id", "workouts", "athlete_shoes", ["shoe_id"], ["id"], ondelete="SET NULL")
    if not column_exists("workouts", "stomach_ok"):
        op.add_column("workouts", sa.Column("stomach_ok", sa.Boolean(), nullable=True))


def downgrade() -> None:
    if column_exists("workouts", "stomach_ok"):
        op.drop_column("workouts", "stomach_ok")
    if column_exists("workouts", "shoe_id"):
        op.drop_constraint("fk_workouts_shoe_id", "workouts", type_="foreignkey")
        op.drop_column("workouts", "shoe_id")
    if table_exists("athlete_shoes"):
        op.drop_index("ix_athlete_shoes_user", table_name="athlete_shoes")
        op.drop_table("athlete_shoes")