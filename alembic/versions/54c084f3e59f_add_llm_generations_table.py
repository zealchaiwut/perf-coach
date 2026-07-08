"""add_llm_generations_table

Revision ID: 54c084f3e59f
Revises: fa2a764aa719
Create Date: 2026-07-06 20:27:22.464651

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

# revision identifiers, used by Alembic.
revision: str = '54c084f3e59f'
down_revision: Union[str, Sequence[str], None] = 'fa2a764aa719'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("llm_generations"):
        return

    op.create_table(
        "llm_generations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(100), nullable=False),
        sa.Column("input_signature", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "surface", "input_signature",
            name="uq_llm_generations_user_surface_sig",
        ),
    )
    op.create_index(
        "ix_llm_generations_user_id",
        "llm_generations",
        ["user_id"],
    )
    op.create_index(
        "ix_llm_generations_user_surface_sig",
        "llm_generations",
        ["user_id", "surface", "input_signature"],
    )


def downgrade() -> None:
    if not table_exists("llm_generations"):
        return

    if index_exists("llm_generations", "ix_llm_generations_user_surface_sig"):
        op.drop_index("ix_llm_generations_user_surface_sig", table_name="llm_generations")
    if index_exists("llm_generations", "ix_llm_generations_user_id"):
        op.drop_index("ix_llm_generations_user_id", table_name="llm_generations")
    op.drop_table("llm_generations")
