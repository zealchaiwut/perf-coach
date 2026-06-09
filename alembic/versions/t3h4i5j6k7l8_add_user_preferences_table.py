"""User preferences table. Single-user shortcut: one row per user, default user gets a row at migration time. FTP/threshold settings move from hardcoded defaults to per-user when set. Multi-user is just adding endpoints — no schema change needed.

Revision ID: t3h4i5j6k7l8
Revises: s2g3h4i5j6k7
Create Date: 2026-06-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from helpers import table_exists, index_exists

revision = "t3h4i5j6k7l8"
down_revision = "s2g3h4i5j6k7"
branch_labels = None
depends_on = None


def upgrade():
    if not table_exists("user_preferences"):
        op.create_table(
            "user_preferences",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_user_preferences_user_id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("ftp_w", sa.Integer(), nullable=True),
            sa.Column("threshold_hr", sa.Integer(), nullable=True),
            sa.Column("threshold_pace_seconds_per_km", sa.Integer(), nullable=True),
            sa.Column(
                "preferred_units",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'metric'"),
            ),
            sa.Column(
                "timezone",
                sa.String(100),
                nullable=False,
                server_default=sa.text("'Asia/Bangkok'"),
            ),
            sa.Column(
                "week_start_day",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("display_name", sa.String(100), nullable=True),
            sa.Column(
                "date_format",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'YYYY-MM-DD'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )

    # Seed one row for the default (first) user if none exists yet
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT COUNT(*) FROM user_preferences")
    ).scalar()
    if existing == 0:
        bind.execute(
            sa.text(
                "INSERT INTO user_preferences (user_id) "
                "SELECT id FROM users ORDER BY created_at LIMIT 1 "
                "ON CONFLICT DO NOTHING"
            )
        )


def downgrade():
    if table_exists("user_preferences"):
        op.drop_table("user_preferences")
