"""users data_version for derived cache invalidation

Revision ID: d8f1c2a39e04
Revises: c7e8a91d2b04
Create Date: 2026-11-22 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists, table_exists

revision: str = "d8f1c2a39e04"
down_revision: Union[str, Sequence[str], None] = "c7e8a91d2b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("users") and not column_exists("users", "data_version"):
        op.add_column(
            "users",
            sa.Column("data_version", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if table_exists("users") and column_exists("users", "data_version"):
        op.drop_column("users", "data_version")