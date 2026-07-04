"""Set DB-level DEFAULT now() on races.updated_at to match the ORM model's
server_default (issue #797).

The ORM already declares ``server_default=text("now()")``, which tells
SQLAlchemy to omit the column from INSERT statements and let the DB supply
the value.  Until this migration runs, the DB column has no DEFAULT, so
new rows end up with ``updated_at = NULL`` in UAT/PRD.

Revision ID: f31dde78c681
Revises: 1c4afa2ab696
Create Date: 2026-07-04 18:46:14.221315
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

from helpers import column_exists, table_exists

revision: str = "f31dde78c681"
down_revision: Union[str, Sequence[str], None] = "1c4afa2ab696"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _updated_at_has_default() -> bool:
    """Return True when races.updated_at already carries a DB-level DEFAULT."""
    bind = op.get_bind()
    inspector = inspect(bind)
    for col in inspector.get_columns("races"):
        if col["name"] == "updated_at":
            return col.get("default") is not None
    return False


def upgrade() -> None:
    if not table_exists("races"):
        return
    if not column_exists("races", "updated_at"):
        return
    if _updated_at_has_default():
        return
    op.execute("ALTER TABLE races ALTER COLUMN updated_at SET DEFAULT now()")


def downgrade() -> None:
    if not table_exists("races"):
        return
    if not column_exists("races", "updated_at"):
        return
    if not _updated_at_has_default():
        return
    op.execute("ALTER TABLE races ALTER COLUMN updated_at DROP DEFAULT")
