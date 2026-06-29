"""add_sleep_records_table

Revision ID: ec0e2c456452
Revises: 15f71886259c
Create Date: 2026-06-27 09:05:11.086660

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists


# revision identifiers, used by Alembic.
revision: str = 'ec0e2c456452'
down_revision: Union[str, Sequence[str], None] = '15f71886259c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = :table "
            "AND constraint_name = :name"
        ),
        {"table": table, "name": name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    if not table_exists("sleep_records"):
        op.create_table(
            "sleep_records",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("sleep_date", sa.Date(), nullable=False),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("total_sleep_minutes", sa.Integer(), nullable=False),
            sa.Column("time_in_bed_minutes", sa.Integer(), nullable=False),
            sa.Column("awake_minutes", sa.Integer(), nullable=False),
            sa.Column("light_minutes", sa.Integer(), nullable=False),
            sa.Column("deep_minutes", sa.Integer(), nullable=False),
            sa.Column("rem_minutes", sa.Integer(), nullable=False),
            sa.Column("sleep_score", sa.Integer(), nullable=True),
            sa.Column("sleep_efficiency", sa.Numeric(5, 2), nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("device", sa.Text(), nullable=True),
            sa.Column("external_id", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name="sleep_records_user_id_fkey",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "user_id", "external_id",
                name="uq_sleep_records_user_external_id",
            ),
        )
        op.create_index(
            "ix_sleep_records_user_sleep_date",
            "sleep_records",
            ["user_id", "sleep_date"],
        )
        return

    # ── Table already exists: apply any missing pieces idempotently ───────────

    if not _constraint_exists("sleep_records", "uq_sleep_records_user_external_id"):
        op.create_unique_constraint(
            "uq_sleep_records_user_external_id",
            "sleep_records",
            ["user_id", "external_id"],
        )

    if not index_exists("sleep_records", "ix_sleep_records_user_sleep_date"):
        op.create_index(
            "ix_sleep_records_user_sleep_date",
            "sleep_records",
            ["user_id", "sleep_date"],
        )


def downgrade() -> None:
    if not table_exists("sleep_records"):
        return

    if index_exists("sleep_records", "ix_sleep_records_user_sleep_date"):
        op.drop_index("ix_sleep_records_user_sleep_date", table_name="sleep_records")

    op.drop_table("sleep_records")
