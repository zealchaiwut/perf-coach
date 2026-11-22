"""stryd_credentials auth_failed_at

Revision ID: c7e8a91d2b04
Revises: 4c9d83c51eaf
Create Date: 2026-11-22 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "c7e8a91d2b04"
down_revision: Union[str, Sequence[str], None] = "4c9d83c51eaf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("stryd_credentials") and not column_exists("stryd_credentials", "auth_failed_at"):
        op.add_column(
            "stryd_credentials",
            sa.Column("auth_failed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if table_exists("stryd_credentials") and column_exists("stryd_credentials", "auth_failed_at"):
        op.drop_column("stryd_credentials", "auth_failed_at")