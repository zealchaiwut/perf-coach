"""merge weight_plans into weight_targets with phase column

S5 schema consolidation (#1604). ``weight_targets`` is the actively-used
table — every real frontend caller (`frontend/js/weight.js`) and every
consumer service (`coach_export.py`, `coach_facts.py`,
`goal_arrival_caller.py`) already read the active *target* (start/target
weight, target date, status history). ``weight_plans`` is a much smaller,
never-wired-to-the-frontend table (`grep -rn "weight-plans" frontend/`
returns nothing) that only carried a ``phase`` (cut/bulk/maintain) and an
optional explicit ``target_rate_kg_per_week``, read by
`backend/routers/fuel.py` (plan-linkage payload) and
`backend/services/cut_review.py` (weekly review).

This migration folds weight_plans' two distinguishing columns onto
weight_targets and retires weight_plans:

1. Add ``phase`` (default 'cut', CHECK IN ('cut','bulk','maintain')) and
   ``target_rate_kg_per_week`` (nullable, same shape as the old column) to
   ``weight_targets``.
2. For every user with an ``active`` weight_plans row:
   - if they also have an ``active`` weight_targets row, copy phase/rate
     onto it;
   - otherwise, create one from the plan's start/goal weight and date.
     ``weight_plans.goal_date`` is nullable (a plan could be rate-only) but
     ``weight_targets.target_date`` is NOT NULL and is load-bearing for the
     rich feature set built on WeightTarget (milestones, progress %,
     required-pace, status label — all assume a target_date exists). Rather
     than weaken that contract for the sake of a handful of never-surfaced
     legacy rows, a missing goal_date is backfilled: implied from the rate
     when one was given, else a conservative flat 180-day placeholder — see
     the SQL below. Only ``active`` plans are migrated; weight_plans never
     had a history view (no such endpoint existed), so inactive rows carry
     no user-visible meaning today and are simply dropped with the table.
   - if a user somehow had more than one ``active`` plan (the app enforced
     single-active only at the application layer, never with a DB
     constraint), only the most recently created one is migrated — matching
     weight_targets' own DB-enforced one-active-per-user rule.
3. Drop ``weight_plans``.

Revision ID: 6f945c183d82
Revises: becc012af2e6
Create Date: 2026-08-01 09:41:41.432667

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

from helpers import column_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = '6f945c183d82'
down_revision: Union[str, Sequence[str], None] = 'becc012af2e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PHASE_CHECK = "ck_weight_targets_phase_values"


def upgrade() -> None:
    """Upgrade schema."""
    if not table_exists("weight_targets"):
        return

    bind = op.get_bind()

    # ── 1. Add the two columns weight_plans contributed ─────────────────────
    if not column_exists("weight_targets", "phase"):
        op.add_column(
            "weight_targets",
            sa.Column("phase", sa.Text(), nullable=False, server_default=text("'cut'")),
        )
    if not column_exists("weight_targets", "target_rate_kg_per_week"):
        op.add_column(
            "weight_targets",
            sa.Column("target_rate_kg_per_week", sa.Numeric(4, 2), nullable=True),
        )

    bind.execute(text(f"ALTER TABLE weight_targets DROP CONSTRAINT IF EXISTS {_PHASE_CHECK}"))
    bind.execute(text(
        f"ALTER TABLE weight_targets ADD CONSTRAINT {_PHASE_CHECK} "
        "CHECK (phase IN ('cut', 'bulk', 'maintain'))"
    ))

    # ── 2. Migrate weight_plans data, if the table still exists ────────────
    if table_exists("weight_plans"):
        # One row per user: the most recently created active plan, if more
        # than one somehow exists (app-level-only exclusivity, never a DB
        # constraint on weight_plans).
        latest_active_plans_sql = """
            SELECT DISTINCT ON (user_id) *
            FROM weight_plans
            WHERE active = true
            ORDER BY user_id, created_at DESC
        """

        # 2a. Users who already have an active weight_target: copy phase/rate.
        bind.execute(text(
            f"""
            UPDATE weight_targets AS wt
            SET phase = wp.phase,
                target_rate_kg_per_week = wp.target_rate_kg_per_week
            FROM ({latest_active_plans_sql}) AS wp
            WHERE wt.user_id = wp.user_id AND wt.status = 'active'
            """
        ))

        # 2b. Users with an active plan but no active target: create one.
        # goal_date fallback, in order: the plan's own goal_date; else
        # implied from |goal - start| / |rate| weeks; else a flat 180-day
        # placeholder (only reachable if a plan somehow had neither a
        # goal_date nor a rate, which the API never allowed).
        bind.execute(text(
            f"""
            INSERT INTO weight_targets (
                id, user_id, start_weight_kg, start_date, target_weight_kg,
                target_date, status, phase, target_rate_kg_per_week, notes,
                created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                wp.user_id,
                wp.start_weight_kg,
                wp.start_date,
                wp.goal_weight_kg,
                COALESCE(
                    wp.goal_date,
                    wp.start_date + (
                        CEIL(
                            ABS(wp.goal_weight_kg - wp.start_weight_kg)
                            / NULLIF(ABS(wp.target_rate_kg_per_week), 0) * 7
                        )
                    )::int * interval '1 day',
                    wp.start_date + interval '180 days'
                ),
                'active',
                wp.phase,
                wp.target_rate_kg_per_week,
                'Migrated from weight_plans (#1604 schema consolidation)',
                now(),
                now()
            FROM ({latest_active_plans_sql}) AS wp
            WHERE NOT EXISTS (
                SELECT 1 FROM weight_targets AS wt
                WHERE wt.user_id = wp.user_id AND wt.status = 'active'
            )
            """
        ))

        # ── 3. Retire weight_plans ───────────────────────────────────────────
        op.drop_table("weight_plans")


def downgrade() -> None:
    """Downgrade schema.

    Recreates an empty ``weight_plans`` table (no data restore — the merge
    is one-directional) and drops the two columns added to weight_targets.
    """
    if not table_exists("weight_targets"):
        return

    if not table_exists("weight_plans"):
        op.create_table(
            "weight_plans",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id", UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("start_weight_kg", sa.Numeric(6, 2), nullable=False),
            sa.Column("goal_weight_kg", sa.Numeric(6, 2), nullable=False),
            sa.Column("goal_date", sa.Date(), nullable=True),
            sa.Column("target_rate_kg_per_week", sa.Numeric(4, 2), nullable=True),
            sa.Column("phase", sa.Text(), nullable=False, server_default=text("'cut'")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=text("now()")),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=text("now()"), onupdate=text("now()"),
            ),
        )
        op.create_index("ix_weight_plans_user_id", "weight_plans", ["user_id"])

    bind = op.get_bind()
    bind.execute(text(f"ALTER TABLE weight_targets DROP CONSTRAINT IF EXISTS {_PHASE_CHECK}"))

    if column_exists("weight_targets", "target_rate_kg_per_week"):
        op.drop_column("weight_targets", "target_rate_kg_per_week")
    if column_exists("weight_targets", "phase"):
        op.drop_column("weight_targets", "phase")
