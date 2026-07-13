"""Add verdict_history table to persist daily training verdicts.

Revision ID: bf3b956dd2e0
Revises: 8b73d5c83348
Create Date: 2026-07-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision = "bf3b956dd2e0"
down_revision = "1da954a27351bb1b"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("verdict_history"):
        return

    op.create_table(
        "verdict_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_verdict_history_user_id"),
            nullable=False,
        ),
        sa.Column("verdict_date", sa.Date(), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("modifiers", postgresql.JSONB(), nullable=True),
        sa.Column("readiness", sa.Float(), nullable=True),
        sa.Column("ctl", sa.Float(), nullable=True),
        sa.Column("atl", sa.Float(), nullable=True),
        sa.Column("tsb", sa.Float(), nullable=True),
        sa.Column("acwr", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "verdict_date", name="uq_verdict_history_user_date"),
    )

    if not index_exists("verdict_history", "ix_verdict_history_user_date"):
        op.execute(
            sa.text(
                "CREATE INDEX ix_verdict_history_user_date "
                "ON verdict_history (user_id, verdict_date DESC)"
            )
        )


def downgrade():
    pass
