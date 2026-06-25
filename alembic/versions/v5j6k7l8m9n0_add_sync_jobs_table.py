"""Add sync_jobs table.

Tracks each activity sync run (Strava, future Stryd) with per-job counters,
status lifecycle, and error capture.

Status lifecycle: pending → running → completed | failed | cancelled

Revision ID: v5j6k7l8m9n0
Revises: u4i5j6k7l8m9
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists, index_exists

revision = "v5j6k7l8m9n0"
down_revision = "u4i5j6k7l8m9"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("sync_jobs"):
        return

    op.create_table(
        "sync_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_sync_jobs_user_id"),
            nullable=False,
        ),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "activities_fetched",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "activities_created",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "activities_updated",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "activities_skipped",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("since_date", sa.Date(), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    if not index_exists("sync_jobs", "ix_sync_jobs_user_source_started_at"):
        op.execute(
            sa.text(
                "CREATE INDEX ix_sync_jobs_user_source_started_at "
                "ON sync_jobs (user_id, source, started_at DESC)"
            )
        )


def downgrade():
    pass
