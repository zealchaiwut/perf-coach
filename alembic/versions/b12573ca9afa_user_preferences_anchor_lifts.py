"""user_preferences anchor_lifts

Revision ID: b12573ca9afa
Revises: bf3569410f9f
Create Date: 2026-11-21 22:55:56.783044

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = 'b12573ca9afa'
down_revision: Union[str, Sequence[str], None] = 'bf3569410f9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Per-user anchor-lift list for the strength axis (P4-4). NULL = use defaults."""
    if table_exists("user_preferences") and not column_exists("user_preferences", "anchor_lifts"):
        op.add_column(
            "user_preferences",
            sa.Column("anchor_lifts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    if table_exists("user_preferences") and column_exists("user_preferences", "anchor_lifts"):
        op.drop_column("user_preferences", "anchor_lifts")
