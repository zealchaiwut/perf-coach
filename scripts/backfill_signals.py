#!/usr/bin/env python3
"""Backfill speed and endurance signals for a user's run workouts (issue #1050).

For each existing run workout belonging to an athlete, this script computes
and stores the speed signal and endurance signal using the same functions
called by the live computation path.

Running the script more than once for the same athlete is safe: the signal
values are pure functions of the workout's splits and the athlete's current
thresholds, so results are identical on repeated calls (idempotent).

Thresholds are always read dynamically from the database.  No threshold value
is hardcoded in this script.

Prerequisites
-------------
  - At least one threshold (ftp_w, threshold_hr, or
    threshold_pace_seconds_per_km) must be set for the athlete in
    user_preferences.
  - The M0 lap classification backfill should be run first so the duration
    curve and lap bands are consistent with current thresholds.

Usage:
    python scripts/backfill_signals.py --user-id <UUID> [--env uat|prd]

Examples:
    python scripts/backfill_signals.py --user-id 123e4567-e89b-12d3-a456-426614174000
    python scripts/backfill_signals.py --user-id <UUID> --env prd
"""

import argparse
import os
import sys
import uuid as _uuid_mod


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill speed and endurance signals for a user's run history."
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="UUID of the athlete whose runs should be backfilled",
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


def _run(engine, user_id_str: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        # Verify the user exists
        row = session.execute(
            text("SELECT id FROM users WHERE id = :uid"),
            {"uid": user_id_str},
        ).first()
        if row is None:
            print(f"ERROR: user {user_id_str} not found", file=sys.stderr)
            sys.exit(1)

        # Check thresholds
        prefs_row = session.execute(
            text(
                "SELECT ftp_w, threshold_hr, threshold_pace_seconds_per_km "
                "FROM user_preferences WHERE user_id = :uid"
            ),
            {"uid": user_id_str},
        ).first()

        if prefs_row is None or (
            prefs_row.ftp_w is None
            and prefs_row.threshold_hr is None
            and prefs_row.threshold_pace_seconds_per_km is None
        ):
            print(
                f"No thresholds set for user {user_id_str}. "
                "Signal backfill requires at least one threshold (ftp_w, threshold_hr, "
                "or threshold_pace_seconds_per_km). Set thresholds in Settings and re-run."
            )
            return

        # Run the backfill
        from backend.services.backfill_signals import backfill_signals_for_athlete

        print(f"Running speed and endurance signal backfill for user {user_id_str}…")
        result = backfill_signals_for_athlete(user_id_str, session)

        print(f"Runs processed:      {result['runs_processed']}")
        print(f"Speed signals computed:     {result['speed_computed']}")
        print(f"Endurance signals computed: {result['endurance_computed']}")
        if result.get("reason"):
            print(f"Note: {result['reason']}")

    print("Backfill complete.")


def main() -> None:
    args = _parse_args()
    user_id_str = args.user_id

    try:
        _uuid_mod.UUID(user_id_str)
    except ValueError:
        print(f"ERROR: --user-id is not a valid UUID: {user_id_str}", file=sys.stderr)
        sys.exit(1)

    try:
        engine = _build_engine(args.env)
    except Exception as exc:
        print(f"FATAL: could not build database engine: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        _run(engine, user_id_str)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
