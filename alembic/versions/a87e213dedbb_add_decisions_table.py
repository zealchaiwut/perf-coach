"""add_decisions_table

Revision ID: a87e213dedbb
Revises: 51a3f6eb0503
Create Date: 2026-07-30 22:10:38.365812

The consult loop's system of record. A check-in produces a ``CHANGES TO APPLY``
block; that block is pasted verbatim into ``raw_text``. No parser — the value is
in having the history at all, so the coach export can carry the last ~10 rows and
the next consult can reference what was already tried.

Lives in the app DB (Neon) rather than Notion or a local file so the record
survives the machine and travels with the export.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import index_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = 'a87e213dedbb'
down_revision: Union[str, Sequence[str], None] = '51a3f6eb0503'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the decisions table."""
    if not table_exists("decisions"):
        op.create_table(
            "decisions",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("decided_on", sa.Date(), nullable=False),
            sa.Column(
                "source", sa.String(20), server_default=sa.text("'consult'"), nullable=False
            ),
            sa.Column("raw_text", sa.Text(), nullable=False),
            sa.Column("tags", postgresql.JSONB(), nullable=True),
            sa.Column(
                "applied", sa.Boolean(), server_default=sa.text("true"), nullable=False
            ),
            sa.Column("outcome_note", sa.Text(), nullable=True),
            sa.Column("review_on", sa.Date(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.CheckConstraint("source IN ('consult')", name="ck_decisions_source_values"),
            sa.CheckConstraint(
                "length(raw_text) > 0", name="ck_decisions_raw_text_non_empty"
            ),
        )

    if table_exists("decisions") and not index_exists(
        "decisions", "ix_decisions_user_decided_on"
    ):
        op.create_index(
            "ix_decisions_user_decided_on",
            "decisions",
            ["user_id", sa.text("decided_on DESC")],
        )


def downgrade() -> None:
    """Drop the decisions table."""
    if table_exists("decisions"):
        if index_exists("decisions", "ix_decisions_user_decided_on"):
            op.drop_index("ix_decisions_user_decided_on", table_name="decisions")
        op.drop_table("decisions")
