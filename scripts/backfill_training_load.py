#!/usr/bin/env python3
"""Backfill training load snapshots (CTL/ATL/TSB/ACWR) for a user.

Delegates to backend.services.training_load.get_snapshot_series() — the
single source of truth for CTL/ATL/TSB/ACWR (see
docs/calculations/training-load.md) — instead of hand-rolling its own EWMA
math. This used to be an independent raw-SQL implementation (hardcoded
42/7, no calibration, no ACWR) that could write snapshot rows inconsistent
with what the app's own endpoints compute; that duplication is exactly what
caused the readiness-cards-vs-coach-report divergence this backfill now
guards against by construction.

Usage:
    python scripts/backfill_training_load.py [--user_id <UUID>] [--env uat|prd]
"""

import argparse
import os
import sys
import uuid as _uuid_mod
from datetime import date


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill CTL/ATL/TSB/ACWR snapshots for a user from workout history."
    )
    parser.add_argument(
        "--user_id",
        default=None,
        help="UUID of the user to backfill (default: first user in users table)",
    )
    parser.add_argument(
        "--env",
        default="uat",
        choices=["uat", "prd"],
        help="Target environment (default: uat)",
    )
    return parser.parse_args()


def _run(user_id_str: str | None = None) -> None:
    # Imported here, after the environment is set in main() — backend.db
    # resolves its engine from ENVIRONMENT/DATABASE_URL at import time.
    from sqlalchemy import text
    from backend.db import engine
    from backend.services.training_load import get_snapshot_series

    with engine.connect() as conn:
        if user_id_str is None:
            row = conn.execute(
                text("SELECT id FROM users ORDER BY created_at LIMIT 1")
            ).first()
            if row is None:
                print("ERROR: no users found in database", file=sys.stderr)
                sys.exit(1)
            user_id = str(row[0])
        else:
            row = conn.execute(
                text("SELECT id FROM users WHERE id = :uid"),
                {"uid": user_id_str},
            ).first()
            if row is None:
                print(f"ERROR: user {user_id_str} not found", file=sys.stderr)
                sys.exit(1)
            user_id = str(row[0])

        earliest_row = conn.execute(
            text(
                "SELECT MIN(workout_date) FROM workouts "
                "WHERE user_id = :uid AND tss IS NOT NULL"
            ),
            {"uid": user_id},
        ).first()

    if earliest_row is None or earliest_row[0] is None:
        print(f"No workouts with TSS found for user {user_id}. Nothing to backfill.")
        return

    earliest = earliest_row[0]
    today = date.today()
    n_days = (today - earliest).days + 1
    print(f"Backfilling {n_days} days from {earliest} to {today}")

    rows = get_snapshot_series(user_id, earliest, today)
    print(f"Wrote {len(rows)} snapshot rows for user {user_id}")


def main() -> None:
    args = _parse_args()

    if args.user_id is not None:
        try:
            _uuid_mod.UUID(args.user_id)
        except ValueError:
            print(f"ERROR: --user_id is not a valid UUID: {args.user_id}", file=sys.stderr)
            sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()
    url_key = f"DATABASE_URL_{args.env.upper()}"
    if not os.getenv(url_key):
        print(f"FATAL: {url_key} is not set in the environment or .env file", file=sys.stderr)
        sys.exit(1)
    # backend.db picks up DATABASE_URL / DATABASE_URL_UAT / DATABASE_URL_PRD
    # by ENVIRONMENT at import time — set both before the first backend import.
    os.environ["ENVIRONMENT"] = args.env
    os.environ.setdefault("DATABASE_URL", os.environ[url_key])

    try:
        _run(args.user_id)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
