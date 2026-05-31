#!/usr/bin/env python3
"""Backfill training load snapshots (CTL/ATL/TSB) for a user.

Computes full Banister impulse-response curves from the user's earliest workout
with TSS to today, then UPSERTs results into training_load_snapshots. Safe to
run repeatedly — uses ON CONFLICT DO UPDATE.

Usage:
    python scripts/backfill_training_load.py [--user_id <UUID>] [--env uat|prd]
"""

import argparse
import math
import os
import sys
import uuid as _uuid_mod
from datetime import date, timedelta


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill CTL/ATL/TSB snapshots for a user from workout history."
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


def _build_engine(env: str):
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    load_dotenv()
    url_key = f"DATABASE_URL_{env.upper()}"
    url = os.getenv(url_key)
    if not url:
        raise RuntimeError(f"{url_key} is not set in the environment or .env file")
    return create_engine(url, pool_pre_ping=True)


def _compute_backfill_rows(
    user_id: str,
    earliest: date,
    tss_by_date: dict,
    today: date,
) -> list[dict]:
    """Pure computation: given TSS data, return list of snapshot row dicts."""
    ctl_alpha = 1 - math.exp(-1 / 42)
    atl_alpha = 1 - math.exp(-1 / 7)
    ctl, atl = 0.0, 0.0
    rows = []
    current = earliest
    while current <= today:
        tss = tss_by_date.get(current, 0)
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        tsb = ctl - atl
        rows.append({
            "user_id": user_id,
            "snapshot_date": current,
            "tss_for_day": tss,
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(tsb, 2),
        })
        current += timedelta(days=1)
    return rows


def _run(engine, user_id_str: str | None = None) -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

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

        tss_rows = conn.execute(
            text(
                """
                SELECT workout_date, COALESCE(SUM(tss), 0)::int AS total_tss
                FROM workouts
                WHERE user_id = :uid
                  AND workout_date BETWEEN :from_d AND :to_d
                  AND tss IS NOT NULL
                GROUP BY workout_date
                """
            ),
            {"uid": user_id, "from_d": earliest, "to_d": today},
        ).fetchall()

        tss_by_date = {row[0]: row[1] for row in tss_rows}

    rows = _compute_backfill_rows(user_id, earliest, tss_by_date, today)

    with engine.connect() as conn:
        for row in rows:
            conn.execute(
                text(
                    """
                    INSERT INTO training_load_snapshots
                        (user_id, snapshot_date, tss_for_day, ctl, atl, tsb)
                    VALUES (:user_id, :snapshot_date, :tss_for_day, :ctl, :atl, :tsb)
                    ON CONFLICT (user_id, snapshot_date) DO UPDATE SET
                        tss_for_day = EXCLUDED.tss_for_day,
                        ctl         = EXCLUDED.ctl,
                        atl         = EXCLUDED.atl,
                        tsb         = EXCLUDED.tsb,
                        computed_at = now()
                    """
                ),
                row,
            )
        conn.commit()


def main() -> None:
    args = _parse_args()

    if args.user_id is not None:
        try:
            _uuid_mod.UUID(args.user_id)
        except ValueError:
            print(f"ERROR: --user_id is not a valid UUID: {args.user_id}", file=sys.stderr)
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
