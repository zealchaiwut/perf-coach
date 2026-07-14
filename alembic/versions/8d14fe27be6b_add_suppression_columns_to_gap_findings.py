"""add suppression columns to gap_findings (issue #1377)

Revision ID: 8d14fe27be6b
Revises: 2bbdfbb8ea10
Create Date: 2026-07-14 12:43:27.383138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from helpers import column_exists

revision: str = "8d14fe27be6b"
down_revision: Union[str, Sequence[str], None] = "2bbdfbb8ea10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("gap_findings", "dismissed_at"):
        op.add_column(
            "gap_findings",
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not column_exists("gap_findings", "dismissed_severity"):
        op.add_column(
            "gap_findings",
            sa.Column("dismissed_severity", sa.Integer, nullable=True),
        )
    if not column_exists("gap_findings", "accepted_at"):
        op.add_column(
            "gap_findings",
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not column_exists("gap_findings", "accepted_evidence_hash"):
        op.add_column(
            "gap_findings",
            sa.Column("accepted_evidence_hash", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    for col in ("accepted_evidence_hash", "accepted_at", "dismissed_severity", "dismissed_at"):
        if column_exists("gap_findings", col):
            op.drop_column("gap_findings", col)
