"""add_exercise_catalog_table

Revision ID: f52d0fe3a9e6
Revises: 54c084f3e59f
Create Date: 2026-07-07 14:46:21.301502

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists

# revision identifiers, used by Alembic.
revision: str = 'f52d0fe3a9e6'
down_revision: Union[str, Sequence[str], None] = '54c084f3e59f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("exercise_catalog"):
        return

    op.create_table(
        "exercise_catalog",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "body_parts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source", sa.String(20), nullable=False, server_default=sa.text("'llm'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_exercise_catalog_name"),
    )
    op.create_index("ix_exercise_catalog_name", "exercise_catalog", ["name"])


def downgrade() -> None:
    if not table_exists("exercise_catalog"):
        return
    op.drop_index("ix_exercise_catalog_name", table_name="exercise_catalog")
    op.drop_table("exercise_catalog")
