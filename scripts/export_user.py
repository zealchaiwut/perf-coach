#!/usr/bin/env python3
"""Copy a single user's data from one perf-coach DB to another (e.g. UAT → PRD).

Walks the reflected FK graph and copies, in dependency order:
  - the `users` row (matched by name),
  - every table that has a `user_id` column (filtered by that user),
  - workout-child tables (`activity_streams`, `workout_exercises`,
    `workout_splits`) filtered by the user's `workout_id`s.

`alembic_version` and `app_config` are never touched.

Idempotent: rows are inserted with ON CONFLICT (pk) DO NOTHING. The destination
keeps the same primary keys (UUIDs), so the copied data references resolve and
the user logs in with the same credentials.

Collision: the destination may already have a different row with the same
`name` (UNIQUE). Pass --delete-existing to remove that destination user (cascade)
before copying.

Usage:
    # dry run (counts only, no writes)
    SRC_URL=$DATABASE_URL_UAT DST_URL=$DATABASE_URL_PRD \
      python scripts/export_user.py --user zeal

    # real copy, replacing any same-name user on the destination
    SRC_URL=$DATABASE_URL_UAT DST_URL=$DATABASE_URL_PRD \
      python scripts/export_user.py --user zeal --delete-existing --commit
"""
import argparse
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()  # pull DATABASE_URL_UAT / DATABASE_URL_PRD from .env if present
except Exception:
    pass

from sqlalchemy import create_engine, text, MetaData, select

SKIP_TABLES = {"alembic_version", "app_config"}
WORKOUT_CHILD = {"activity_streams", "workout_exercises", "workout_splits"}


def _host(url: str) -> str:
    return url.split("@")[-1].split("/")[0] if "@" in url else url


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True, help="users.name to copy")
    ap.add_argument("--commit", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--delete-existing", action="store_true",
                    help="delete a same-name user on the destination first (cascade)")
    args = ap.parse_args()

    # SRC_URL/DST_URL win; otherwise fall back to the UAT/PRD names from .env.
    src_url = os.environ.get("SRC_URL") or os.environ.get("DATABASE_URL_UAT")
    dst_url = os.environ.get("DST_URL") or os.environ.get("DATABASE_URL_PRD")
    if not src_url or not dst_url:
        print(
            "ERROR: no DB URLs. Either run from a dir with a .env containing\n"
            "  DATABASE_URL_UAT / DATABASE_URL_PRD, or pass them explicitly:\n"
            "  SRC_URL=... DST_URL=... python scripts/export_user.py --user zeal",
            file=sys.stderr,
        )
        return 2
    if _host(src_url) == _host(dst_url):
        print("ERROR: SRC and DST point at the same host — refusing", file=sys.stderr)
        return 2

    src = create_engine(src_url)
    dst = create_engine(dst_url)
    md = MetaData()
    md.reflect(bind=src)

    print(f"SRC {_host(src_url)}  →  DST {_host(dst_url)}")
    print(f"user: {args.user}   mode: {'COMMIT' if args.commit else 'dry-run'}")

    with src.connect() as sc:
        urow = sc.execute(text("SELECT id FROM users WHERE name = :n"), {"n": args.user}).first()
        if not urow:
            print(f"ERROR: no user named {args.user!r} in source", file=sys.stderr)
            return 1
        uid = urow[0]
        wids = [r[0] for r in sc.execute(
            text("SELECT id FROM workouts WHERE user_id = :u"), {"u": uid})]
    print(f"source user id = {uid}   workouts = {len(wids)}")

    # Plan: ordered list of (table, where-clause, params)
    plan = []
    for t in md.sorted_tables:
        name = t.name
        if name in SKIP_TABLES:
            continue
        cols = {c.name for c in t.columns}
        if name == "users":
            plan.append((t, "id = :uid", {"uid": uid}))
        elif "user_id" in cols:
            plan.append((t, "user_id = :uid", {"uid": uid}))
        elif name in WORKOUT_CHILD and "workout_id" in cols:
            plan.append((t, None, None))  # filtered by wids in code

    dconn = dst.connect()
    trans = dconn.begin()
    try:
        if args.delete_existing:
            existing = dconn.execute(text("SELECT id FROM users WHERE name = :n"), {"n": args.user}).first()
            if existing:
                print(f"  deleting destination user {existing[0]} (cascade)…")
                dconn.execute(text("DELETE FROM users WHERE name = :n"), {"n": args.user})

        with src.connect() as sc:
            total = 0
            for t, where, params in plan:
                q = select(t)
                if where is not None:
                    q = q.where(text(where).bindparams(**params))
                elif t.name in WORKOUT_CHILD:
                    if not wids:
                        print(f"  {t.name:30} 0 (no workouts)")
                        continue
                    q = q.where(t.c.workout_id.in_(wids))
                rows = [dict(r._mapping) for r in sc.execute(q)]
                if rows:
                    pk = [c.name for c in t.primary_key.columns]
                    if args.commit:
                        # psycopg/pg: use ON CONFLICT DO NOTHING via raw for safety
                        from sqlalchemy.dialects.postgresql import insert as pg_insert
                        stmt = pg_insert(t).values(rows)
                        if pk:
                            stmt = stmt.on_conflict_do_nothing(index_elements=pk)
                        dconn.execute(stmt)
                    total += len(rows)
                print(f"  {t.name:30} {len(rows)}")
            print(f"  total rows: {total}")

        if args.commit:
            trans.commit()
            print("COMMITTED.")
        else:
            trans.rollback()
            print("dry-run — rolled back, nothing written.")
    except Exception:
        trans.rollback()
        raise
    finally:
        dconn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
