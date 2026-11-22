"""weekly_check_ins_p6_12

Revision ID: 482fc3199b4e
Revises: e4ce8c710624
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from helpers import table_exists

revision: str = "482fc3199b4e"
down_revision: Union[str, Sequence[str], None] = "e4ce8c710624"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("weekly_check_ins"):
        op.create_table(
            "weekly_check_ins",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("week_start", sa.Date(), nullable=False),
            sa.Column("snapshot", JSONB, nullable=True),
            sa.Column("carried_changes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("feet", sa.Integer(), nullable=True),
            sa.Column("bed_bucket", sa.String(10), nullable=True),
            sa.Column("motivation", sa.String(10), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("feet IS NULL OR (feet >= 0 AND feet <= 3)", name="ck_weekly_check_ins_feet"),
            sa.CheckConstraint(
                "bed_bucket IS NULL OR bed_bucket IN ('0-2', '3-4', '5-7')",
                name="ck_weekly_check_ins_bed_bucket",
            ),
            sa.CheckConstraint(
                "motivation IS NULL OR motivation IN ('low', 'ok', 'high')",
                name="ck_weekly_check_ins_motivation",
            ),
            sa.UniqueConstraint("user_id", "week_start", name="uq_weekly_check_ins_user_week"),
        )


def downgrade() -> None:
    if table_exists("weekly_check_ins"):
        op.drop_table("weekly_check_ins")