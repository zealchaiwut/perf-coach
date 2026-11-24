"""pwa_session_template_overrides

Revision ID: d95d4d98684a
Revises: bffa23e7b071
Create Date: 2026-11-24 15:49:29.321423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from helpers import table_exists

revision: str = "d95d4d98684a"
down_revision: Union[str, Sequence[str], None] = "bffa23e7b071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("session_template_overrides"):
        op.create_table(
            "session_template_overrides",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("template_key", sa.String(120), nullable=False),
            sa.Column("exercise_key", sa.String(160), nullable=False),
            sa.Column("override", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("user_id", "template_key", "exercise_key", name="uq_session_template_overrides"),
        )
        op.create_index("ix_session_template_overrides_user", "session_template_overrides", ["user_id"])


def downgrade() -> None:
    if table_exists("session_template_overrides"):
        op.drop_table("session_template_overrides")
