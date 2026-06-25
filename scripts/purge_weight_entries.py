#!/usr/bin/env python3
"""Purge weight entries matching a date ceiling and a weight ceiling.

Usage:
    python scripts/purge_weight_entries.py --before DATE --below KG [--dry-run]

Both --before and --below are required.  Without --dry-run the script prompts for
confirmation before deleting anything.

Examples:
    # Preview rows that would be deleted
    python scripts/purge_weight_entries.py --before 2025-01-01 --below 79 --dry-run

    # Delete with confirmation prompt
    python scripts/purge_weight_entries.py --before 2025-01-01 --below 79
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Purge weight_entries rows older than DATE and lighter than KG."
    )
    parser.add_argument(
        "--before",
        required=True,
        metavar="DATE",
        help="Delete entries with entry_date < DATE (ISO YYYY-MM-DD)",
    )
    parser.add_argument(
        "--below",
        required=True,
        type=float,
        metavar="KG",
        help="Delete entries with weight_kg < KG",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print count of affected rows without modifying data",
    )
    return parser.parse_args()


def _build_engine():
    environment = os.getenv("ENVIRONMENT", "local").lower()
    database_url = os.getenv("DATABASE_URL") or (
        os.getenv("DATABASE_URL_UAT") if environment == "uat" else os.getenv("DATABASE_URL_PRD")
    )
    if not database_url:
        print(
            "ERROR: No DATABASE_URL found in environment. "
            "Set DATABASE_URL or DATABASE_URL_UAT/DATABASE_URL_PRD.",
            file=sys.stderr,
        )
        sys.exit(1)

    from sqlalchemy import create_engine
    return create_engine(database_url, pool_pre_ping=True)


def main() -> None:
    args = _parse_args()

    try:
        before_date = datetime.date.fromisoformat(args.before)
    except ValueError:
        print(f"ERROR: --before must be ISO date (YYYY-MM-DD), got: {args.before!r}", file=sys.stderr)
        sys.exit(1)

    below_kg = args.below

    from sqlalchemy import text

    engine = _build_engine()

    count_sql = text(
        "SELECT COUNT(*) FROM weight_entries "
        "WHERE entry_date < :before AND weight_kg < :below"
    )
    delete_sql = text(
        "DELETE FROM weight_entries "
        "WHERE entry_date < :before AND weight_kg < :below"
    )
    params = {"before": before_date, "below": below_kg}

    with engine.connect() as conn:
        row_count = conn.execute(count_sql, params).scalar()

    print(
        f"{'[dry-run] ' if args.dry_run else ''}"
        f"{row_count} rows match "
        f"(entry_date < {before_date}, weight_kg < {below_kg} kg)"
    )

    if args.dry_run:
        print("Dry-run complete — no data modified.")
        return

    if row_count == 0:
        print("No rows to delete.")
        return

    answer = input("Confirm deletion? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted — no rows deleted.")
        return

    with engine.connect() as conn:
        conn.execute(delete_sql, params)
        conn.commit()

    print(f"Deleted {row_count} rows.")


if __name__ == "__main__":
    main()
