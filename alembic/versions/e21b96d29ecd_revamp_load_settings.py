"""revamp_load_settings

Revision ID: e21b96d29ecd
Revises: b72b310448b8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from helpers import table_exists

revision: str = "e21b96d29ecd"
down_revision: Union[str, Sequence[str], None] = "b72b310448b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("revamp_load_settings"):
        op.create_table(
            "revamp_load_settings",
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("a_race_id", sa.UUID(), nullable=True),
            sa.Column("block_start", sa.Date(), nullable=True),
            sa.Column("phase", JSONB(), nullable=True),
            sa.Column("peak_tss", sa.Float(), nullable=True),
            sa.Column("max_consecutive_days", sa.Integer(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["a_race_id"], ["races.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("user_id"),
        )


def downgrade() -> None:
    if table_exists("revamp_load_settings"):
        op.drop_table("revamp_load_settings")