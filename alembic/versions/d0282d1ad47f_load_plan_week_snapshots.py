"""load plan week snapshots

Revision ID: d0282d1ad47f
Revises: dff094694e51
Create Date: 2026-11-20 16:27:52.800644

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from helpers import table_exists

revision: str = "d0282d1ad47f"
down_revision: Union[str, Sequence[str], None] = "dff094694e51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("load_plan_week_snapshots"):
        op.create_table(
            "load_plan_week_snapshots",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("week_start", sa.Date(), nullable=False),
            sa.Column("target_tss", sa.Float(), nullable=False),
            sa.Column("phase", sa.String(20), nullable=False),
            sa.Column("peak_tss", sa.Float(), nullable=True),
            sa.Column("settings_fingerprint", sa.String(16), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("user_id", "week_start", name="uq_load_plan_week_snapshots_user_week"),
        )


def downgrade() -> None:
    if table_exists("load_plan_week_snapshots"):
        op.drop_table("load_plan_week_snapshots")