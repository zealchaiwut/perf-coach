"""race tss if override

Revision ID: 4b2875119331
Revises: d0282d1ad47f
Create Date: 2026-11-20 17:14:45.966802

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "4b2875119331"
down_revision: Union[str, Sequence[str], None] = "d0282d1ad47f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("races", "tss_if_override"):
        op.add_column("races", sa.Column("tss_if_override", sa.Numeric(4, 3), nullable=True))


def downgrade() -> None:
    if column_exists("races", "tss_if_override"):
        op.drop_column("races", "tss_if_override")