"""add_last_sync_at_to_google_oauth_credentials

Revision ID: 2814c5b30dc7
Revises: ec0e2c456452
Create Date: 2026-06-27 09:47:37.664531

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = '2814c5b30dc7'
down_revision: Union[str, Sequence[str], None] = 'ec0e2c456452'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("google_oauth_credentials", "last_sync_at"):
        op.add_column(
            "google_oauth_credentials",
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if column_exists("google_oauth_credentials", "last_sync_at"):
        op.drop_column("google_oauth_credentials", "last_sync_at")
