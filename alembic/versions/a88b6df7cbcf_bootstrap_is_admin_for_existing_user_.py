"""bootstrap is_admin for existing user (revamp P5-5)

Promote the earliest-created user when no admin exists yet (single-tenant bootstrap).

Revision ID: a88b6df7cbcf
Revises: 040c0bcc655a
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a88b6df7cbcf"
down_revision: Union[str, Sequence[str], None] = "040c0bcc655a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET is_admin = true
        WHERE id = (
            SELECT id FROM users ORDER BY created_at ASC NULLS LAST, name ASC LIMIT 1
        )
        AND NOT EXISTS (SELECT 1 FROM users WHERE is_admin = true)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET is_admin = false
        WHERE id = (
            SELECT id FROM users ORDER BY created_at ASC NULLS LAST, name ASC LIMIT 1
        )
        AND NOT EXISTS (
            SELECT 1 FROM users WHERE is_admin = true AND id <> (
                SELECT id FROM users ORDER BY created_at ASC NULLS LAST, name ASC LIMIT 1
            )
        )
        """
    )