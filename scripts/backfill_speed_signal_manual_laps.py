#!/usr/bin/env python3
"""Recompute + persist speed_signal for run workouts (issue #1240).

Interval sessions store their real hard efforts as Stryd manual-lap presses in
the streams, not as the 1 km auto-splits in workout_splits. The auto-splits
average reps+recovery together and sit below threshold, so those workouts had
speed_signal = None and never fed the Speed score. speed_signal.py now prefers
the manual-lap reps (falling back to the auto-splits when they don't qualify);
this script re-runs that computation over existing history so the historical
interval sessions get repopulated.

Scope: every run workout with a stryd_activity_pk (the runs whose manual laps
we can recover). Non-Stryd runs are left untouched. Idempotent — the result is
a pure function of the streams + current thresholds, so re-running is safe.

Delegates to compute_and_store_speed_signal (the live path) so the script and
the app never drift.

Usage:
    python scripts/backfill_speed_signal_manual_laps.py [--env uat|prd]
                                                        [--user-id <UUID>]
                                                        [--dry-run]

--user-id limits the backfill to one athlete; omit to process all athletes.
--dry-run computes and reports the flips without committing.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Recompute speed_signal for Stryd run workouts (manual-lap path)."
    )
    p.add_argument("--env", default="uat", choices=["uat", "prd"],
                   help="Target environment (default: uat)")
    p.add_argument("--user-id", default=None,
                   help="Limit to one athlete UUID (default: all athletes)")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute and report without committing")
    return p.parse_args()


def _build_engine(env: str):
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    load_dotenv()
    url_key = f"DATABASE_URL_{env.upper()}"
    url = os.getenv(url_key)
    if not url:
        raise RuntimeError(f"{url_key} is not set in the environment or .env file")
    return create_engine(url, pool_pre_ping=True)


def _run(engine, user_id, dry_run: bool) -> None:
    from sqlalchemy.orm import Session
    from backend.models import Workout
    from backend.services.speed_signal import compute_and_store_speed_signal

    with Session(engine) as session:
        q = session.query(Workout).filter(
            Workout.workout_type == "run",
            Workout.stryd_activity_pk.isnot(None),
        )
        if user_id:
            q = q.filter(Workout.user_id == user_id)
        runs = q.order_by(Workout.workout_date).all()

        processed = 0
        flipped_none_to_value = 0
        changed_value = 0
        failed = 0

        for w in runs:
            before = w.speed_signal
            ok, reason = compute_and_store_speed_signal(w.id, session)
            processed += 1
            if not ok:
                failed += 1
                print(f"  skip {w.id} ({w.name!r}): {reason}", file=sys.stderr)
                continue
            after = w.speed_signal
            if before is None and after is not None:
                flipped_none_to_value += 1
                print(f"  None -> {after}  {w.workout_date}  {w.name!r}  ({w.speed_signal_source})")
            elif before is not None and after is not None and abs(float(before) - float(after)) > 1e-9:
                changed_value += 1

        if dry_run:
            session.rollback()
        else:
            session.commit()

        print()
        print(f"Env:                     {ENV}")
        print(f"Stryd run workouts:      {len(runs)}")
        print(f"Processed:               {processed}")
        print(f"None -> value (new):     {flipped_none_to_value}")
        print(f"Value changed:           {changed_value}")
        print(f"Failed/skipped:          {failed}")
        print(f"Committed:               {not dry_run}")


ENV = "uat"


def main() -> None:
    global ENV
    args = _parse_args()
    ENV = args.env
    try:
        engine = _build_engine(args.env)
    except Exception as exc:
        print(f"FATAL: could not build database engine: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        _run(engine, args.user_id, args.dry_run)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
