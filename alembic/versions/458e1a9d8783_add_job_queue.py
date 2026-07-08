"""add job_queue

Neon-backed pull queue so the compute worker (behind home NAT) can claim work
instead of being reached over HTTP. Separate from worker_job_runs (the execution
audit trail). See backend/models.py JobQueue + backend/services/job_queue.py.

Revision ID: 458e1a9d8783
Revises: f52d0fe3a9e6
Create Date: 2026-07-08 13:03:18.925380

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = '458e1a9d8783'
down_revision: Union[str, Sequence[str], None] = 'f52d0fe3a9e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not table_exists("job_queue"):
        op.create_table(
            "job_queue",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("job_type", sa.String(length=40), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.Column("status", sa.String(length=12), server_default=sa.text("'queued'"), nullable=False),
            sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
            sa.Column("claimed_by", sa.String(length=120), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("worker_job_run_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("enqueued_by", sa.String(length=12), nullable=True),
            sa.Column("dedupe_key", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_foreign_key(
            "job_queue_worker_job_run_id_fkey", "job_queue", "worker_job_runs",
            ["worker_job_run_id"], ["id"], ondelete="SET NULL",
        )

    # Partial indexes (idempotent via IF NOT EXISTS) — match backend/models.py.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_queue_claim ON job_queue "
        "(priority, created_at) WHERE status = 'queued'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_queue_lease ON job_queue "
        "(lease_expires_at) WHERE status = 'running'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_queue_dedupe ON job_queue "
        "(dedupe_key) WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_job_queue_dedupe")
    op.execute("DROP INDEX IF EXISTS ix_job_queue_lease")
    op.execute("DROP INDEX IF EXISTS ix_job_queue_claim")
    if table_exists("job_queue"):
        op.drop_table("job_queue")
