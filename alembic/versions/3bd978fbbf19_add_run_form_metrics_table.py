"""add_run_form_metrics_table

Extract per-run Stryd running-dynamics (GCT, LSS, vertical oscillation, cadence,
power) from stryd_activities.form_metrics JSONB into a queryable table (issue #1368).

Revision ID: 3bd978fbbf19
Revises: bf3b956dd2e0
Create Date: 2026-07-13 18:56:10.702656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from helpers import column_exists, table_exists, index_exists, fk_exists

revision: str = "3bd978fbbf19"
down_revision: Union[str, None] = "bf3b956dd2e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("run_form_metrics"):
        return

    op.create_table(
        "run_form_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stryd_activity_pk", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("gct_ms", sa.Numeric(8, 2), nullable=True),
        sa.Column("lss_kn_m", sa.Numeric(8, 4), nullable=True),
        sa.Column("vertical_oscillation_cm", sa.Numeric(6, 2), nullable=True),
        sa.Column("cadence_spm", sa.Numeric(6, 2), nullable=True),
        sa.Column("power_w", sa.Numeric(6, 1), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stryd_activity_pk", name="uq_run_form_metrics_stryd_activity_pk"),
    )

    op.create_foreign_key(
        "run_form_metrics_user_id_fkey",
        "run_form_metrics",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "run_form_metrics_workout_id_fkey",
        "run_form_metrics",
        "workouts",
        ["workout_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "run_form_metrics_stryd_activity_pk_fkey",
        "run_form_metrics",
        "stryd_activities",
        ["stryd_activity_pk"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_run_form_metrics_user_run_date",
        "run_form_metrics",
        ["user_id", "run_date"],
    )


def downgrade() -> None:
    if not table_exists("run_form_metrics"):
        return

    for idx in ["ix_run_form_metrics_user_run_date"]:
        if index_exists("run_form_metrics", idx):
            op.drop_index(idx, table_name="run_form_metrics")

    op.drop_table("run_form_metrics")
