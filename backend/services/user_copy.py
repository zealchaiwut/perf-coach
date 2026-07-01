"""Copy a single user's full data graph from the PRD database into UAT.

This generalises the one-off restore we did by hand: pick a user that exists in
PRD and clone every row they own into UAT, preserving UUID primary keys so all
foreign-key links (workout -> exercises/splits, workout -> strava/stryd activity)
stay intact. Inserts use ON CONFLICT (id) DO NOTHING, so it is idempotent and
safe to re-run.

Direction is hard-locked PRD -> UAT. The target is always resolved from
DATABASE_URL_UAT and we refuse to run if the resolved target equals the PRD
url, so this can never write into PRD by mistake.
"""
from __future__ import annotations

import os
from typing import Optional

from sqlalchemy import create_engine, text
from psycopg2.extras import Json


class UserCopyError(RuntimeError):
    """Raised for expected, user-facing failures (misconfig, user not found)."""


# FK-safe insertion order. Parents before children:
#  - strava/stryd activities before workouts (workouts FK their activity pk)
#  - habits/workouts before their child rows
_USER_TABLES = [
    "users",
    "habits",
    "strava_activities",
    "stryd_activities",
    "workouts",
    "weight_entries",
    "daily_metrics",
    "personal_records",
    "sleep_imports",
    "training_load_snapshots",
    "strava_tokens",
    "stryd_credentials",
    "google_oauth_credentials",
    "workout_feel",
    "daily_readiness",
    "habit_logs",
]
_CHILD_BY_WORKOUT = ["workout_exercises", "workout_splits"]


def _colnames(conn, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_name=:t order by ordinal_position"
            ),
            {"t": table},
        )
    ]


def _adapt(value):
    # psycopg2 cannot adapt a bare dict/list into a jsonb param.
    return Json(value) if isinstance(value, (dict, list)) else value


def _resolve_urls() -> tuple[str, str]:
    prd = os.getenv("DATABASE_URL_PRD")
    uat = os.getenv("DATABASE_URL_UAT")
    if not prd or not uat:
        raise UserCopyError(
            "Both DATABASE_URL_PRD and DATABASE_URL_UAT must be set to copy a "
            "user. This feature only runs where both are configured (e.g. the "
            "local/self-hosted dashboard), not on a single-DATABASE_URL host."
        )
    if prd == uat:
        raise UserCopyError("PRD and UAT database urls are identical; refusing to run.")
    return prd, uat


def find_prd_user(identifier: str) -> Optional[dict]:
    """Look up a user in PRD by exact name or by UUID. Returns id/name/flags."""
    prd, _ = _resolve_urls()
    eng = create_engine(prd)
    with eng.connect() as c:
        row = c.execute(
            text(
                "select id, name, is_active, is_admin, created_at from users "
                "where name = :ident or cast(id as text) = :ident"
            ),
            {"ident": identifier},
        ).mappings().first()
    return dict(row) if row else None


def list_prd_users() -> list[dict]:
    """List PRD users (id, name, flags) for the copy picker, name-sorted."""
    prd, _ = _resolve_urls()
    eng = create_engine(prd)
    with eng.connect() as c:
        rows = c.execute(
            text(
                "select id, name, is_active, is_admin, created_at from users "
                "order by lower(name)"
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def copy_user_to_uat(identifier: str, *, overwrite: bool = False) -> dict:
    """Copy the PRD user identified by name or UUID into UAT.

    Returns a per-table count of rows inserted. Raises UserCopyError for
    expected failures (misconfig, user missing, or already present without
    overwrite). The whole copy runs in one transaction.
    """
    prd_url, uat_url = _resolve_urls()
    prd = create_engine(prd_url)
    uat = create_engine(uat_url)

    user = find_prd_user(identifier)
    if user is None:
        raise UserCopyError(f"No PRD user matches '{identifier}'.")
    zid = str(user["id"])

    with uat.connect() as c:
        exists = c.execute(
            text("select 1 from users where id = :z"), {"z": zid}
        ).first()
    if exists and not overwrite:
        raise UserCopyError(
            f"User '{user['name']}' ({zid}) already exists in UAT. "
            "Pass overwrite=True to re-run (existing rows are kept; only missing "
            "rows are added)."
        )

    total: dict[str, int] = {}
    with prd.connect() as p, uat.begin() as u:
        wids = [
            r[0]
            for r in p.execute(
                text("select id from workouts where user_id = :z"), {"z": zid}
            )
        ]

        def copy(table: str, where: str, params: dict) -> None:
            cols = [c for c in _colnames(u, table) if c in set(_colnames(p, table))]
            rows = (
                p.execute(text(f"select {','.join(cols)} from {table} where {where}"), params)
                .mappings()
                .all()
            )
            if not rows:
                total[table] = 0
                return
            stmt = text(
                f"insert into {table} ({','.join(cols)}) "
                f"values ({','.join(':' + c for c in cols)}) "
                f"on conflict (id) do nothing"
            )
            u.execute(stmt, [{k: _adapt(v) for k, v in dict(r).items()} for r in rows])
            total[table] = len(rows)

        for t in _USER_TABLES:
            copy(t, "id = :z" if t == "users" else "user_id = :z", {"z": zid})
        for t in _CHILD_BY_WORKOUT:
            if wids:
                copy(t, "workout_id = any(:ids)", {"ids": wids})
            else:
                total[t] = 0

    return {"user": {"id": zid, "name": user["name"]}, "copied": total}
