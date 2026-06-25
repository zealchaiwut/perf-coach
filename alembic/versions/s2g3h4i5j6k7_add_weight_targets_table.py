"""Add weight_targets table for per-user weight goals with status history.

Status transition rules:
  active → achieved  (user reached their goal weight)
  active → abandoned (user gave up on the goal)
  active → replaced  (a new goal superseded this one)

Immutability: start_weight_kg records the weight at goal creation and must not
be updated after insert; application-layer enforcement is deferred to a future
ticket — this migration establishes the column and intent only.

Gain goals: target_weight_kg > start_weight_kg (e.g. bulking) is explicitly
permitted. No check constraint restricts the direction of the goal.

Revision ID: s2g3h4i5j6k7
Revises: r1f2g3h4i5j6
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from helpers import table_exists, index_exists

revision = "s2g3h4i5j6k7"
down_revision = "r1f2g3h4i5j6"
branch_labels = None
depends_on = None


def _check_constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.table_constraints "
        "WHERE table_schema = 'public' AND table_name = :t "
        "AND constraint_name = :n AND constraint_type = 'CHECK'"
    ), {"t": table, "n": name}).scalar()
    return result > 0


def upgrade():
    if not table_exists("weight_targets"):
        op.create_table(
            "weight_targets",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_weight_targets_user_id"),
                nullable=False,
            ),
            sa.Column("start_weight_kg", sa.Numeric(5, 2), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("target_weight_kg", sa.Numeric(5, 2), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_weight_kg", sa.Numeric(5, 2), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
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
            sa.CheckConstraint(
                "status IN ('active', 'achieved', 'abandoned', 'replaced')",
                name="ck_weight_targets_status_values",
            ),
        )

    if not index_exists("weight_targets", "ix_weight_targets_user_status"):
        op.create_index(
            "ix_weight_targets_user_status",
            "weight_targets",
            ["user_id", "status"],
        )

    if not index_exists("weight_targets", "uix_weight_targets_one_active_per_user"):
        op.execute(sa.text(
            "CREATE UNIQUE INDEX uix_weight_targets_one_active_per_user "
            "ON weight_targets (user_id) WHERE status = 'active'"
        ))


def downgrade():
    if not table_exists("weight_targets"):
        return

    if index_exists("weight_targets", "uix_weight_targets_one_active_per_user"):
        op.execute(sa.text(
            "DROP INDEX IF EXISTS uix_weight_targets_one_active_per_user"
        ))

    if index_exists("weight_targets", "ix_weight_targets_user_status"):
        op.drop_index("ix_weight_targets_user_status", table_name="weight_targets")

    op.drop_table("weight_targets")
