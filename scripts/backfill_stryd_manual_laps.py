"""Backfill stryd_activities.manual_laps from stored stream payloads.

manual_laps has been computed at SYNC time since issue #1295 — every
activity synced before that has streams but a NULL manual_laps, so the
performance score's rep-level speed extraction can't see the athlete's
lap-button reps on historical runs. This recomputes them once, using the
same compute_manual_laps the sync path uses. Zero network calls; safe to
re-run (only touches rows where manual_laps IS NULL, or all with --force).

Usage:
    ENVIRONMENT=uat python3 scripts/backfill_stryd_manual_laps.py [--env uat] [--force]
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=["uat", "prd"], default=os.environ.get("ENVIRONMENT", "uat"))
    parser.add_argument("--force", action="store_true", help="recompute even when manual_laps already set")
    args = parser.parse_args()

    os.environ["ENVIRONMENT"] = args.env
    db_url_key = f"DATABASE_URL_{args.env.upper()}"
    if os.environ.get(db_url_key) and not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ[db_url_key]

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.services.stryd_laps import compute_manual_laps

    where = "streams_payload IS NOT NULL" + ("" if args.force else " AND manual_laps IS NULL")
    with Session(engine) as db:
        ids = [r[0] for r in db.execute(text(f"SELECT id FROM stryd_activities WHERE {where}")).fetchall()]
    print(f"{len(ids)} activities to backfill")

    updated = empty = failed = 0
    # One row per transaction: streams payloads are large — keep memory flat
    # and make interrupts harmless.
    for i, aid in enumerate(ids, 1):
        try:
            with Session(engine) as db:
                streams = db.execute(
                    text("SELECT streams_payload FROM stryd_activities WHERE id = :id"),
                    {"id": aid},
                ).scalar()
                laps = compute_manual_laps(streams)
                db.execute(
                    text("UPDATE stryd_activities SET manual_laps = CAST(:laps AS jsonb) WHERE id = :id"),
                    {"laps": __import__("json").dumps(laps), "id": aid},
                )
                db.commit()
            if laps:
                updated += 1
            else:
                empty += 1
        except Exception as e:  # keep going — one corrupt payload shouldn't stop the rest
            failed += 1
            print(f"  FAILED {aid}: {e}")
        if i % 25 == 0:
            print(f"  {i}/{len(ids)} (with laps: {updated}, empty: {empty}, failed: {failed})")

    print(f"done: {updated} with laps, {empty} empty (no lap presses), {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
