"""add_economy_ceiling_snapshots_table

Revision ID: 02ea347c3bd1
Revises: b1dc2caab43e
Create Date: 2026-06-30 18:24:48.813504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = '02ea347c3bd1'
down_revision: Union[str, Sequence[str], None] = 'b1dc2caab43e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create economy_ceiling_snapshots table (idempotent)."""
    if table_exists("economy_ceiling_snapshots"):
        return

    op.create_table(
        "economy_ceiling_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "economy_stimulus",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column(
            "ceiling_bonus",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="economy_ceiling_snapshots_user_id_fkey",
        ),
        sa.UniqueConstraint(
            "user_id",
            "snapshot_date",
            name="uq_economy_ceiling_snapshots_user_date",
        ),
        sa.CheckConstraint(
            "economy_stimulus >= 0",
            name="ck_economy_ceiling_snapshots_stimulus_non_negative",
        ),
        sa.CheckConstraint(
            "ceiling_bonus >= 0",
            name="ck_economy_ceiling_snapshots_bonus_non_negative",
        ),
    )
    op.create_index(
        "ix_economy_ceiling_snapshots_user_date",
        "economy_ceiling_snapshots",
        ["user_id", "snapshot_date"],
    )


def downgrade() -> None:
    """Drop economy_ceiling_snapshots table."""
    if not table_exists("economy_ceiling_snapshots"):
        return

    op.drop_index(
        "ix_economy_ceiling_snapshots_user_date",
        table_name="economy_ceiling_snapshots",
    )
    op.drop_table("economy_ceiling_snapshots")
