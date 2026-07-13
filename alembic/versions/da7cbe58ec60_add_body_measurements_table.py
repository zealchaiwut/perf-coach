"""add_body_measurements_table

Revision ID: da7cbe58ec60
Revises: bf3b956dd2e0
Create Date: 2026-07-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision = "da7cbe58ec60"
down_revision = "bf3b956dd2e0"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("body_measurements"):
        return

    op.create_table(
        "body_measurements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_body_measurements_user_id"),
            nullable=False,
        ),
        sa.Column("measure_date", sa.Date(), nullable=False),
        sa.Column("waist_cm", sa.Numeric(5, 1), nullable=True),
        sa.Column("body_fat_pct", sa.Numeric(4, 1), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "measure_date", name="uq_body_measurements_user_date"),
        sa.CheckConstraint("source IN ('manual', 'imported')", name="ck_body_measurements_source"),
    )

    if not index_exists("body_measurements", "ix_body_measurements_user_date"):
        op.create_index(
            "ix_body_measurements_user_date",
            "body_measurements",
            ["user_id", "measure_date"],
        )


def downgrade():
    pass
