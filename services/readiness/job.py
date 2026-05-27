"""
Readiness computation job.

Reads daily_metrics rows from the database, calls compute_readiness,
and upserts the result into daily_readiness.

Can be run as a CLI for backfilling:

    python -m services.readiness.job --user-id <uuid> --date 2026-05-27
    python -m services.readiness.job --user-id <uuid> --from 2026-01-01 --to 2026-05-27
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from services.readiness.calculator import HRV_WINDOW, RHR_WINDOW, compute_readiness


def _fetch_baseline(
    conn,
    user_id: str,
    target_date: date,
    column: str,
    window: int,
) -> list[float]:
    rows = conn.execute(
        text(
            f"SELECT {column} FROM daily_metrics "
            "WHERE user_id = :uid "
            "  AND metric_date >= :start AND metric_date < :end "
            f"  AND {column} IS NOT NULL "
            "ORDER BY metric_date"
        ),
        {
            "uid": user_id,
            "start": str(target_date - timedelta(days=window)),
            "end": str(target_date),
        },
    ).fetchall()
    return [float(r[0]) for r in rows]


def compute_and_store(user_id: str, target_date: date) -> Optional[dict]:
    """
    Compute readiness for (user_id, target_date) and upsert into daily_readiness.

    Returns the persisted row as a dict, or None if no metric row exists for the date.
    """
    with Session(engine) as session:
        metric_row = session.execute(
            text(
                "SELECT id, hrv, resting_hr, sleep_quality, energy "
                "FROM daily_metrics "
                "WHERE user_id = :uid AND metric_date = :d"
            ),
            {"uid": user_id, "d": str(target_date)},
        ).fetchone()

        if metric_row is None:
            return None

        metric_id = str(metric_row.id)
        hrv_baseline = _fetch_baseline(session, user_id, target_date, "hrv", HRV_WINDOW)
        rhr_baseline = _fetch_baseline(session, user_id, target_date, "resting_hr", RHR_WINDOW)

        result = compute_readiness(
            hrv=float(metric_row.hrv) if metric_row.hrv is not None else None,
            resting_hr=float(metric_row.resting_hr) if metric_row.resting_hr is not None else None,
            sleep_quality=float(metric_row.sleep_quality) if metric_row.sleep_quality is not None else None,
            energy=float(metric_row.energy) if metric_row.energy is not None else None,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
        )

        if result is None:
            return None

        components_json = json.dumps({
            "hrv_contribution": result.components.hrv_contribution,
            "rhr_contribution": result.components.rhr_contribution,
            "sleep_contribution": result.components.sleep_contribution,
            "energy_contribution": result.components.energy_contribution,
        })

        # Upsert: insert or update existing row for (user_id, date)
        session.execute(
            text("""
                INSERT INTO daily_readiness (user_id, date, score, components, computed_at, daily_metric_id)
                VALUES (:uid, :d, :score, :components::jsonb, now(), :metric_id)
                ON CONFLICT (user_id, date) DO UPDATE SET
                    score = EXCLUDED.score,
                    components = EXCLUDED.components,
                    computed_at = EXCLUDED.computed_at,
                    daily_metric_id = EXCLUDED.daily_metric_id
            """),
            {
                "uid": user_id,
                "d": str(target_date),
                "score": float(result.score),
                "components": components_json,
                "metric_id": metric_id,
            },
        )
        session.commit()

        row = session.execute(
            text(
                "SELECT id, user_id, date, score, components, computed_at, daily_metric_id "
                "FROM daily_readiness WHERE user_id = :uid AND date = :d"
            ),
            {"uid": user_id, "d": str(target_date)},
        ).fetchone()

        return {
            "id": str(row.id),
            "user_id": str(row.user_id),
            "date": str(row.date),
            "score": float(row.score),
            "components": row.components,
            "computed_at": row.computed_at.isoformat(),
            "daily_metric_id": str(row.daily_metric_id) if row.daily_metric_id else None,
        }


def _date_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute and store daily readiness scores")
    parser.add_argument("--user-id", required=True, help="User UUID")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="Single date (YYYY-MM-DD)")
    group.add_argument("--from", dest="from_date", help="Start of date range (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", help="End of date range (YYYY-MM-DD, inclusive)")
    args = parser.parse_args()

    if args.date:
        dates = [date.fromisoformat(args.date)]
    else:
        if not args.to_date:
            parser.error("--to is required when using --from")
        dates = list(_date_range(
            date.fromisoformat(args.from_date),
            date.fromisoformat(args.to_date),
        ))

    inserted = 0
    skipped = 0
    for d in dates:
        row = compute_and_store(args.user_id, d)
        if row:
            print(f"  {d}  score={row['score']:.2f}")
            inserted += 1
        else:
            skipped += 1

    print(f"\nDone. Computed: {inserted}, skipped (no metric row): {skipped}")


if __name__ == "__main__":
    main()
