#!/usr/bin/env python3
"""One-shot backfill script for historical readiness scores.

Iterates every daily_metrics row for a given user, computes a readiness score
using the same algorithm as the live pipeline, and persists the result
idempotently to daily_readiness.

Usage:
    python scripts/backfill_readiness.py --user-id <UUID> [--env uat|prd]
"""

import argparse
import json
import os
import sys
import uuid as _uuid_mod


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill readiness scores for a user from existing daily_metrics rows."
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="UUID of the user whose readiness scores should be backfilled",
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


def _compute_readiness(hrv, resting_hr, sleep_hours, sleep_quality, energy, mood):
    """Mirrors backend._compute_readiness(); returns (score | None, components_dict)."""
    components = {}
    values = []

    if hrv is not None:
        v = min(100.0, max(0.0, (float(hrv) - 20.0) / 80.0 * 100.0))
        components["hrv_contribution"] = round(v, 4)
        values.append(v)
    if resting_hr is not None:
        v = max(0.0, min(100.0, (90.0 - float(resting_hr)) * 2.0))
        components["rhr_contribution"] = round(v, 4)
        values.append(v)
    if sleep_hours is not None:
        v = max(0.0, min(100.0, (float(sleep_hours) - 4.0) / 5.0 * 100.0))
        components["sleep_contribution"] = round(v, 4)
        values.append(v)
    if sleep_quality is not None:
        v = (float(sleep_quality) - 1.0) / 4.0 * 100.0
        components["sleep_quality_contribution"] = round(v, 4)
        values.append(v)
    if energy is not None:
        v = (float(energy) - 1.0) / 4.0 * 100.0
        components["energy_contribution"] = round(v, 4)
        values.append(v)
    if mood is not None:
        v = (float(mood) - 1.0) / 4.0 * 100.0
        components["mood_contribution"] = round(v, 4)
        values.append(v)

    if not values:
        return None, {}

    score = round(sum(values) / len(values))
    return score, components


def main() -> None:
    args = _parse_args()

    try:
        user_uuid = _uuid_mod.UUID(args.user_id)
    except ValueError:
        print(f"ERROR: --user-id is not a valid UUID: {args.user_id}", file=sys.stderr)
        sys.exit(1)

    print(f"[backfill_readiness] env={args.env.upper()}  user_id={user_uuid}")

    try:
        engine = _build_engine(args.env)
    except Exception as exc:
        print(f"FATAL: could not build database engine: {exc}", file=sys.stderr)
        sys.exit(1)

    total = 0
    scored = 0           # days where a readiness score could be computed
    newly_inserted = 0   # days where a new row was written (vs already existed)
    skipped = []         # list of (date_str, reason_str) for days with no score

    try:
        from sqlalchemy import text
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            user_row = session.execute(
                text("SELECT id FROM users WHERE id = :uid"),
                {"uid": str(user_uuid)},
            ).first()
            if user_row is None:
                print(
                    f"FATAL: user {user_uuid} not found in {args.env.upper()} database",
                    file=sys.stderr,
                )
                sys.exit(1)

            metrics = session.execute(
                text(
                    """
                    SELECT id, metric_date, hrv, resting_hr,
                           sleep_hours, sleep_quality, energy, mood
                    FROM daily_metrics
                    WHERE user_id = :uid
                    ORDER BY metric_date
                    """
                ),
                {"uid": str(user_uuid)},
            ).fetchall()

            for row in metrics:
                total += 1
                metric_id, metric_date, hrv, resting_hr, sleep_hours, sleep_quality, energy, mood = row

                score, components = _compute_readiness(
                    hrv, resting_hr, sleep_hours, sleep_quality, energy, mood
                )

                if score is None:
                    skipped.append(
                        (str(metric_date), "all metric fields are null — cannot compute score")
                    )
                    continue

                result = session.execute(
                    text(
                        """
                        INSERT INTO daily_readiness
                            (user_id, date, score, components, daily_metric_id)
                        VALUES
                            (:uid, :date, :score, CAST(:components AS jsonb), :metric_id)
                        ON CONFLICT (user_id, date) DO NOTHING
                        """
                    ),
                    {
                        "uid": str(user_uuid),
                        "date": metric_date,
                        "score": score,
                        "components": json.dumps(components),
                        "metric_id": str(metric_id),
                    },
                )
                scored += 1
                if result.rowcount > 0:
                    newly_inserted += 1

            session.commit()

    except SystemExit:
        raise
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)

    already_existed = scored - newly_inserted
    print()
    print(f"=== Backfill complete ({args.env.upper()}) ===")
    print(f"  Total days processed : {total}")
    print(f"  Days scored          : {scored}  (new: {newly_inserted}, already existed: {already_existed})")
    print(f"  Days skipped         : {len(skipped)}")
    if skipped:
        print()
        print("  Skipped days:")
        for date_str, reason in skipped:
            print(f"    {date_str}: {reason}")


if __name__ == "__main__":
    main()
