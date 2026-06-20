"""add_strength_personal_records_and_achievements

Revision ID: a1607bab81de
Revises: z9n0o1p2q3r4
Create Date: 2026-06-20 08:12:02.652075

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1607bab81de'
down_revision: Union[str, Sequence[str], None] = 'z9n0o1p2q3r4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    from sqlalchemy import inspect as _inspect
    conn = op.get_bind()
    return _inspect(conn).has_table(name)


def upgrade() -> None:
    if not _table_exists("strength_personal_records"):
        op.create_table(
            "strength_personal_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("exercise_key", sa.String(200), nullable=False),
            sa.Column("exercise_name", sa.String(200), nullable=False),
            sa.Column("rep_band_label", sa.String(20), nullable=False),
            sa.Column("rep_band_min", sa.Integer(), nullable=False),
            sa.Column("rep_band_max", sa.Integer(), nullable=False),
            sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
            sa.Column("reps", sa.Integer(), nullable=False),
            sa.Column("previous_weight_kg", sa.Numeric(6, 2), nullable=True),
            sa.Column("previous_achieved_on", sa.Date(), nullable=True),
            sa.Column("achieved_on", sa.Date(), nullable=False),
            sa.Column("workout_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["exercise_id"], ["workout_exercises.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "exercise_key", "rep_band_label", name="uq_strength_pr_user_exercise_band"),
            sa.CheckConstraint("weight_kg > 0", name="ck_strength_pr_weight_positive"),
            sa.CheckConstraint("reps >= 1", name="ck_strength_pr_reps_positive"),
        )

    if not _table_exists("strength_record_achievements"):
        op.create_table(
            "strength_record_achievements",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("strength_record_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("exercise_key", sa.String(200), nullable=False),
            sa.Column("exercise_name", sa.String(200), nullable=False),
            sa.Column("rep_band_label", sa.String(20), nullable=False),
            sa.Column("new_weight_kg", sa.Numeric(6, 2), nullable=False),
            sa.Column("previous_weight_kg", sa.Numeric(6, 2), nullable=True),
            sa.Column("previous_achieved_on", sa.Date(), nullable=True),
            sa.Column("achieved_on", sa.Date(), nullable=False),
            sa.Column("workout_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("set_index", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["strength_record_id"], ["strength_personal_records.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["exercise_id"], ["workout_exercises.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    if _table_exists("strength_record_achievements"):
        op.drop_table("strength_record_achievements")
    if _table_exists("strength_personal_records"):
        op.drop_table("strength_personal_records")
