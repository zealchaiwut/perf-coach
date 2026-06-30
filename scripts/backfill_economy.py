#!/usr/bin/env python3
"""Backfill economy model across historical strength and plyo sessions (issue #1149).

Computes economy stimulus and lagged ceiling bonus for every historical strength
and plyometric session in the database, then UPSERTs the results into
``economy_ceiling_snapshots``.  Safe to run repeatedly — idempotent.

Usage:
    python scripts/backfill_economy.py [--user_id <UUID>] [--env uat|prd]

Options:
    --user_id   UUID of a specific user (default: all active users)
    --env       Target environment: uat or prd (default: uat)
"""

import argparse
import os
import sys
import uuid as _uuid_mod


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill economy ceiling snapshots from historical sessions."
    )
    parser.add_argument(
        "--user_id",
        default=None,
        help="UUID of the user to backfill (default: all active users)",
    )
    parser.add_argument(
        "--env",
        default="uat",
        choices=["uat", "prd"],
        help="Target environment (default: uat)",
    )
    return parser.parse_args()


def _build_engine(env: str):
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    load_dotenv()
    url_key = f"DATABASE_URL_{env.upper()}"
    url = os.getenv(url_key)
    if not url:
        raise RuntimeError(f"{url_key} is not set in the environment or .env file")
    return create_engine(url, pool_pre_ping=True)


def _run(engine, user_id_str: str | None = None) -> None:
    from sqlalchemy import text

    from backend.services.backfill_economy import backfill_economy_for_user

    with engine.connect() as conn:
        # Resolve user list
        if user_id_str is not None:
            row = conn.execute(
                text("SELECT id FROM users WHERE id = :uid"),
                {"uid": user_id_str},
            ).first()
            if row is None:
                print(f"ERROR: user {user_id_str} not found", file=sys.stderr)
                sys.exit(1)
            user_ids = [str(row[0])]
        else:
            rows = conn.execute(
                text("SELECT id FROM users WHERE is_active = true ORDER BY created_at")
            ).fetchall()
            if not rows:
                print("No active users found. Nothing to backfill.")
                return
            user_ids = [str(r[0]) for r in rows]

        print(f"Backfilling economy model for {len(user_ids)} user(s).")

        total_processed = 0
        total_written = 0

        for uid in user_ids:
            summary = backfill_economy_for_user(uid, conn)
            conn.commit()
            print(
                f"  user={uid}: "
                f"strength_dates={summary['strength_dates']}, "
                f"plyo_dates={summary['plyo_dates']}, "
                f"sessions_processed={summary['sessions_processed']}, "
                f"snapshots_written={summary['snapshots_written']}"
            )
            total_processed += summary["sessions_processed"]
            total_written += summary["snapshots_written"]

        print(
            f"\nDone. Total sessions processed: {total_processed}, "
            f"snapshots written: {total_written}."
        )


def main() -> None:
    args = _parse_args()

    if args.user_id is not None:
        try:
            _uuid_mod.UUID(args.user_id)
        except ValueError:
            print(
                f"ERROR: --user_id is not a valid UUID: {args.user_id}",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        engine = _build_engine(args.env)
    except Exception as exc:
        print(f"FATAL: could not build database engine: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        _run(engine, args.user_id)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
