"""add_worker_job_runs_table

Revision ID: a7812835b558
Revises: f32591c408cf
Create Date: 2026-07-05 23:14:17.521585

Persisted job-run tracking for the new compute worker (strava_sync,
stryd_sync, backfill, banister_refit, ...). Idempotent: guarded by
table_exists so it is a no-op where the table already exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = 'a7812835b558'
down_revision: Union[str, Sequence[str], None] = 'f32591c408cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if table_exists("worker_job_runs"):
        return

    op.create_table(
        "worker_job_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("job_type", sa.String(length=30), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=10),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(length=30), nullable=True),
        sa.Column(
            "items_synced",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "triggered_by",
            sa.String(length=10),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_foreign_key(
        "worker_job_runs_user_id_fkey",
        "worker_job_runs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_worker_job_runs_user_started_at "
        "ON worker_job_runs (user_id, started_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_worker_job_runs_job_type_started_at "
        "ON worker_job_runs (job_type, started_at)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_worker_job_runs_job_type_started_at")
    op.execute("DROP INDEX IF EXISTS ix_worker_job_runs_user_started_at")
    if table_exists("worker_job_runs"):
        op.drop_table("worker_job_runs")
