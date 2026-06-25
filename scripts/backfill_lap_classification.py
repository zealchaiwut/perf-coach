#!/usr/bin/env python3
"""Backfill lap classification for a user's run workouts.

For each existing run workout belonging to an athlete, this script classifies
laps using the athlete's current thresholds (read from user_preferences),
then rebuilds the athlete's best-effort duration curve (AthleteDurationCurve).

Running the script more than once for the same athlete is safe: the duration
curve merge always selects the best value at each duration, so results are
identical on repeated calls (idempotent).

Manually entered values (manual_overrides on Workout, lap_type="manual" on
WorkoutSplit) are read but never overwritten.

Thresholds are always read dynamically from the database.  No threshold value
is hardcoded in this script.

Usage:
    python scripts/backfill_lap_classification.py --user-id <UUID> [--env uat|prd]

Examples:
    python scripts/backfill_lap_classification.py --user-id 123e4567-e89b-12d3-a456-426614174000
    python scripts/backfill_lap_classification.py --user-id <UUID> --env prd
"""

import argparse
import os
import sys
import uuid as _uuid_mod


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill lap classification and rebuild duration curve for a user."
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
    from backend.services.lap_recompute import rebuild_athlete_duration_curve
    from backend.services.lap_classify import classify_laps

    with Session(engine) as session:
        # Verify the user exists
        row = session.execute(
            text("SELECT id FROM users WHERE id = :uid"),
            {"uid": user_id_str},
        ).first()
        if row is None:
            print(f"ERROR: user {user_id_str} not found", file=sys.stderr)
            sys.exit(1)

        # Read thresholds dynamically from DB (never hardcoded)
        from sqlalchemy import text as _text
        prefs_row = session.execute(
            _text(
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
                "Lap classification requires at least one threshold (ftp_w, threshold_hr, "
                "or threshold_pace_seconds_per_km). Duration curve will still be refreshed."
            )

        # Step 1: Report how many run workouts exist for this user
        count_row = session.execute(
            _text(
                "SELECT COUNT(*) FROM workouts "
                "WHERE user_id = :uid AND workout_type ILIKE '%run%'"
            ),
            {"uid": user_id_str},
        ).first()
        n_runs = count_row[0] if count_row else 0
        print(f"Found {n_runs} run workout(s) for user {user_id_str}.")

        if n_runs == 0:
            print("Nothing to backfill.")
            return

        # Step 2: Classify laps in-memory for diagnostic output
        from backend.models import Workout, WorkoutSplit, UserPreferences
        run_workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == user_id_str,
                Workout.workout_type.ilike("%run%"),
            )
            .order_by(Workout.workout_date.asc())
            .all()
        )

        prefs_obj = (
            session.query(UserPreferences)
            .filter(UserPreferences.user_id == user_id_str)
            .first()
        )
        prefs_dict = {
            "ftp_w": prefs_obj.ftp_w if prefs_obj else None,
            "threshold_hr": prefs_obj.threshold_hr if prefs_obj else None,
            "threshold_pace_seconds_per_km": (
                prefs_obj.threshold_pace_seconds_per_km if prefs_obj else None
            ),
        }

        classified_count = 0
        skipped_count = 0
        for workout in run_workouts:
            splits = (
                session.query(WorkoutSplit)
                .filter(WorkoutSplit.workout_id == workout.id)
                .order_by(WorkoutSplit.split_index)
                .all()
            )
            if not splits:
                skipped_count += 1
                continue
            classifications = classify_laps(splits, prefs_dict)
            classified_count += 1
            bands = [c.get("band") for c in classifications]
            classified_laps = sum(1 for b in bands if b is not None)
            print(
                f"  Workout {workout.id} ({workout.workout_date}): "
                f"{len(splits)} split(s), {classified_laps} classified"
            )

        print(
            f"Classified {classified_count} workout(s) in-memory "
            f"({skipped_count} had no splits — skipped)."
        )

        # Step 3: Rebuild the athlete's best-effort duration curve from all run workouts.
        # This is the persistent step: updates AthleteDurationCurve for this athlete.
        print("Rebuilding best-effort duration curve…")
        curve, reason = rebuild_athlete_duration_curve(user_id_str, session)
        if reason is not None:
            print(f"Warning: duration curve rebuild returned: {reason}")
        else:
            print(f"Duration curve refreshed ({len(curve)} duration windows).")

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
