"""derive habit_type from tracking_type and dedupe habits uniqueness

Two independent fixes on the same table, both from the S5 schema-consolidation
review (#1604):

1. Backfill ``habit_type`` from ``tracking_type`` for every existing row.
   ``tracking_type`` is the survivor column going forward — the application
   write path (``backend/services/habits_repo.py``) now derives
   ``habit_type`` from it at create time instead of taking whatever the
   caller supplied. This backfill makes existing rows consistent with that
   rule; it is a no-op for rows that already agree (which is most rows —
   the goal-habit and coach-tracked-habit seeders already write matching
   pairs) and corrects the ones that don't (habits created through the real
   frontend never sent ``habit_type`` at all, so they silently got the
   column's server default of 'binary' regardless of their real tracking
   type).

2. Add two partial-unique indexes on ``habits`` closing the check-then-insert
   race in ``ensure_goal_habits`` (confirmed live on the UAT DB: concurrent
   requests produced duplicate "Morning weigh-in", "Protein first" and
   "Long-run fuel" rows for the same user). The lookup that must never
   double-insert (``goal_habits._find``) matches by ``auto_fill_source``
   first when the spec has one, else falls back to matching by ``name`` —
   so the constraint has to cover both keys:

   - ``auto_fill_source`` alone is not enough: "Protein first" has no
     auto-fill source (it's self-reported), so a duplicate of it would sail
     straight through a unique index on ``(user_id, auto_fill_source)``
     with both rows NULL.
   - a plain ``UNIQUE (user_id, name)`` would break legitimate re-creation
     after archiving (``_find`` filters ``is_archived = false``, so an
     athlete archiving a habit and creating a new one with the same name is
     allowed). Both indexes below are partial on ``WHERE is_archived =
     false`` for exactly that reason.

   Before either index can be created, any duplicates already sitting in the
   table (per the confirmation above) are deduplicated: for each colliding
   group the earliest-created row is kept, its siblings' habit_logs are
   re-pointed onto it (skipping any (habit_id, log_date) that would collide
   with a log the survivor already has — extremely rare, and never a
   destructive delete), and the siblings are archived rather than deleted so
   no history disappears from the database, only from the active list.

Revision ID: becc012af2e6
Revises: 8cefa13354c8
Create Date: 2026-08-01 09:41:35.437569

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from helpers import index_exists, table_exists


# revision identifiers, used by Alembic.
revision: str = 'becc012af2e6'
down_revision: Union[str, Sequence[str], None] = '8cefa13354c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_AUTO_FILL_SOURCE_INDEX = "uq_habits_user_id_auto_fill_source_active"
_NAME_INDEX = "uq_habits_user_id_name_active"


def _dedupe_habits(bind, key_column: str, extra_where: str = "") -> None:
    """Keep the earliest-created non-archived habit per (user_id, key_column);
    re-point its siblings' logs onto it and archive the siblings.

    Idempotent: once a group has been reduced to one non-archived row, it no
    longer appears in the GROUP BY HAVING COUNT(*) > 1 result on a re-run.
    """
    where_extra = f" AND {extra_where}" if extra_where else ""
    dupe_groups = bind.execute(text(
        f"""
        SELECT user_id, {key_column} AS key_val
        FROM habits
        WHERE is_archived = false{where_extra}
        GROUP BY user_id, {key_column}
        HAVING COUNT(*) > 1
        """
    )).fetchall()

    now = datetime.now(timezone.utc)

    for group in dupe_groups:
        rows = bind.execute(text(
            f"""
            SELECT id
            FROM habits
            WHERE is_archived = false
              AND user_id = :uid
              AND {key_column} IS NOT DISTINCT FROM :key_val
            ORDER BY created_at ASC, id ASC
            """
        ), {"uid": group.user_id, "key_val": group.key_val}).fetchall()

        winner_id = rows[0].id
        loser_ids = [r.id for r in rows[1:]]

        for loser_id in loser_ids:
            # Move logs that don't collide with a log the winner already has
            # on the same date. habit_logs has a UNIQUE(habit_id, log_date),
            # so a straight re-point can't be done unconditionally.
            bind.execute(text(
                """
                UPDATE habit_logs AS hl
                SET habit_id = :winner_id
                WHERE hl.habit_id = :loser_id
                  AND NOT EXISTS (
                      SELECT 1 FROM habit_logs AS hl2
                      WHERE hl2.habit_id = :winner_id
                        AND hl2.log_date = hl.log_date
                  )
                """
            ), {"winner_id": winner_id, "loser_id": loser_id})

            # Archive rather than delete — any logs left behind (same-date
            # collisions with the winner, if any) stay attached to the
            # archived row rather than being destroyed.
            bind.execute(text(
                """
                UPDATE habits
                SET is_archived = true, active = false, archived_at = :now
                WHERE id = :loser_id
                """
            ), {"loser_id": loser_id, "now": now})


def upgrade() -> None:
    """Upgrade schema."""
    if not table_exists("habits"):
        return

    bind = op.get_bind()

    # ── 1. Backfill habit_type from tracking_type ──────────────────────────
    bind.execute(text(
        """
        UPDATE habits
        SET habit_type = CASE tracking_type
            WHEN 'daily_checkmark' THEN 'binary'
            WHEN 'weekly_minutes'  THEN 'duration'
            WHEN 'weekly_count'    THEN 'count'
            WHEN 'weekly_quantity' THEN 'count'
            ELSE habit_type
        END
        WHERE tracking_type IN
            ('daily_checkmark', 'weekly_minutes', 'weekly_count', 'weekly_quantity')
        """
    ))

    # ── 2. Dedupe before the uniqueness indexes can be created ─────────────
    if not index_exists("habits", _AUTO_FILL_SOURCE_INDEX):
        _dedupe_habits(bind, "auto_fill_source", extra_where="auto_fill_source IS NOT NULL")
    if not index_exists("habits", _NAME_INDEX):
        _dedupe_habits(bind, "name")

    # ── 3. Partial unique indexes matching ensure_goal_habits._find's lookup ─
    if not index_exists("habits", _AUTO_FILL_SOURCE_INDEX):
        op.execute(text(
            f"CREATE UNIQUE INDEX {_AUTO_FILL_SOURCE_INDEX} "
            "ON habits (user_id, auto_fill_source) "
            "WHERE is_archived = false AND auto_fill_source IS NOT NULL"
        ))

    if not index_exists("habits", _NAME_INDEX):
        op.execute(text(
            f"CREATE UNIQUE INDEX {_NAME_INDEX} "
            "ON habits (user_id, name) "
            "WHERE is_archived = false"
        ))


def downgrade() -> None:
    """Downgrade schema.

    Drops the two indexes only. The habit_type backfill and the dedupe
    archiving are not reversed — there is no prior value recorded to restore
    habit_type to, and un-archiving the deduped rows would silently
    resurrect the exact race-condition duplicates this migration exists to
    remove.
    """
    if not table_exists("habits"):
        return

    if index_exists("habits", _NAME_INDEX):
        op.execute(text(f"DROP INDEX IF EXISTS {_NAME_INDEX}"))

    if index_exists("habits", _AUTO_FILL_SOURCE_INDEX):
        op.execute(text(f"DROP INDEX IF EXISTS {_AUTO_FILL_SOURCE_INDEX}"))
