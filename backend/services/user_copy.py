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

from cryptography.fernet import Fernet, InvalidToken
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


# ── Full-environment copy (Deploy-tab "Copy PRD → UAT" feature) ───────────────
#
# copy_user_to_uat above is the surgical, one-user admin tool and stays exactly
# as it is. copy_all_users_to_uat below is a different operation: sync EVERY
# PRD user into UAT, updating rows that already exist there (not just filling
# in what's missing) so UAT becomes a true snapshot of PRD's current state —
# the Deploy tab's use case is "I found a bug in PRD, get that data into UAT
# to reproduce it," not a one-time seed.
#
# It does not delete UAT-only rows (e.g. rows created directly in UAT for
# testing) that have no PRD counterpart — only rows that exist in PRD are
# touched, via ON CONFLICT (id) DO UPDATE. That is a deliberate, more
# conservative choice than a full mirror; a UAT-only row is not evidence of
# anything wrong with PRD's data and deleting it isn't needed to reproduce a
# PRD bug.

# Fernet-encrypted columns that need decrypt(prd-key)/re-encrypt(uat-key)
# treatment during a cross-environment copy — copying ciphertext verbatim
# leaves it undecryptable wherever the two environments' keys differ (see
# _fernet_for's PRD/UAT key resolution below).
_ENCRYPTED_COLUMNS: dict[str, dict[str, str]] = {
    "stryd_credentials": {"stryd_password_encrypted": "STRYD_FERNET_KEY"},
    "strava_tokens": {
        "access_token_encrypted": "OAUTH_FERNET_KEY",
        "refresh_token_encrypted": "OAUTH_FERNET_KEY",
    },
    "google_oauth_credentials": {
        "access_token_encrypted": "OAUTH_FERNET_KEY",
        "refresh_token_encrypted": "OAUTH_FERNET_KEY",
    },
}


def _fernet_for(key_name: str, side: str) -> Optional[Fernet]:
    """Return a Fernet for *key_name* (e.g. "STRYD_FERNET_KEY") on the "prd"
    or "uat" side of the copy.

    Prefers an explicit ``<KEY>_PRD`` / ``<KEY>_UAT`` env var — the split this
    feature actually needs, since PRD and UAT can use different keys. Falls
    back to the plain, unsuffixed ``<KEY>`` var (today's single-key setup on
    every environment this runs from locally) so this works before the
    operator has split the keys out; that fallback is a real limitation
    against Render-hosted production, whose real key isn't available from any
    local .env at all unless deliberately copied there — see the
    encryption_failures list in copy_all_users_to_uat's return value, which
    is how a genuine key mismatch or missing key surfaces instead of
    silently writing broken ciphertext.
    """
    value = os.getenv(f"{key_name}_{side.upper()}") or os.getenv(key_name)
    if not value:
        return None
    return Fernet(value.encode() if isinstance(value, str) else value)


def reencrypt_row(table: str, row: dict, encryption_failures: list[dict]) -> dict:
    """Return *row* with any Fernet-encrypted columns re-keyed from PRD's key
    to UAT's key (see _ENCRYPTED_COLUMNS / _fernet_for).

    A column that can't be re-keyed (no key configured, or decrypt fails
    because the keys don't actually match) is set to None in the returned
    row, and an entry describing why is appended to *encryption_failures* —
    the caller surfaces that list to the operator. Every other column is
    passed through unchanged. A table with no encrypted columns is returned
    as-is (same dict, not a defensive copy — callers that need one make it
    themselves, matching how this is used in copy_all_users_to_uat).
    """
    enc_cols = _ENCRYPTED_COLUMNS.get(table)
    if not enc_cols:
        return row
    out = dict(row)
    for col, key_name in enc_cols.items():
        ciphertext = out.get(col)
        if not ciphertext:
            continue
        prd_fernet = _fernet_for(key_name, "prd")
        uat_fernet = _fernet_for(key_name, "uat")
        if prd_fernet is None or uat_fernet is None:
            out[col] = None
            encryption_failures.append({
                "table": table, "column": col, "row_id": str(out.get("id")),
                "reason": f"{key_name} (or {key_name}_PRD/{key_name}_UAT) not configured",
            })
            continue
        raw = ciphertext.encode() if isinstance(ciphertext, str) else ciphertext
        try:
            plaintext = prd_fernet.decrypt(raw)
            out[col] = uat_fernet.encrypt(plaintext).decode()
        except InvalidToken:
            out[col] = None
            encryption_failures.append({
                "table": table, "column": col, "row_id": str(out.get("id")),
                "reason": "decrypt failed with the configured prd key — keys do not match",
            })
    return out


def copy_all_users_to_uat() -> dict:
    """Sync every PRD user's full data graph into UAT (see module note above).

    Returns:
      {
        "users_copied": int,
        "copied": {table: row_count, ...},
        "encryption_failures": [{"table", "column", "row_id", "reason"}, ...],
      }

    An encryption_failures entry means that field was written as NULL in UAT
    rather than left as unusable ciphertext — the corresponding integration
    (Stryd/Strava/Google) will show as disconnected in UAT and need
    reconnecting there; every other field for that row still copied normally.
    """
    prd_url, uat_url = _resolve_urls()
    prd = create_engine(prd_url)
    uat = create_engine(uat_url)

    encryption_failures: list[dict] = []
    total: dict[str, int] = {}

    with prd.connect() as p, uat.begin() as u:
        users_copied = p.execute(text("select count(*) from users")).scalar() or 0

        def copy_all(table: str, where: str, params: dict) -> int:
            cols = [c for c in _colnames(u, table) if c in set(_colnames(p, table))]
            rows = (
                p.execute(text(f"select {','.join(cols)} from {table} where {where}"), params)
                .mappings().all()
            )
            if not rows:
                return 0
            update_cols = [c for c in cols if c != "id"]
            set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
            stmt = text(
                f"insert into {table} ({','.join(cols)}) "
                f"values ({','.join(':' + c for c in cols)}) "
                f"on conflict (id) do update set {set_clause}"
            )
            payload = [
                {k: _adapt(v) for k, v in reencrypt_row(table, dict(r), encryption_failures).items()}
                for r in rows
            ]
            u.execute(stmt, payload)
            return len(rows)

        for t in _USER_TABLES:
            total[t] = copy_all(t, "true", {})

        wids = [r[0] for r in p.execute(text("select id from workouts"))]
        for t in _CHILD_BY_WORKOUT:
            total[t] = copy_all(t, "workout_id = any(:ids)", {"ids": wids}) if wids else 0

    return {
        "users_copied": users_copied,
        "copied": total,
        "encryption_failures": encryption_failures,
    }
