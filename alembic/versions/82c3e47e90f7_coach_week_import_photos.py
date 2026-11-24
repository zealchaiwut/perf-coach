"""coach_week_import_photos

Revision ID: 82c3e47e90f7
Revises: e21b96d29ecd
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import table_exists

revision: str = "82c3e47e90f7"
down_revision: Union[str, Sequence[str], None] = "e21b96d29ecd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("coach_week_import_photos"):
        op.create_table(
            "coach_week_import_photos",
            sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("week_start", sa.Date(), nullable=False),
            sa.Column("mime", sa.String(80), nullable=False),
            sa.Column("data", sa.LargeBinary(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "week_start", name="uq_coach_week_import_photos_user_week"),
        )


def downgrade() -> None:
    if table_exists("coach_week_import_photos"):
        op.drop_table("coach_week_import_photos")