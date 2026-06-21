"""Backfill Stryd per-point streams for past activities.

Manual laps and any per-point interval stats are computed from a Stryd
activity's ``streams_payload``. Older activities were enriched before streams
capture existed, so they have per-km ``splits`` but no ``streams_payload`` — the
normal sync skips re-enriching them (the "already enriched" shortcut keys on
``splits``). This one-off re-fetches the streams for every Stryd activity in a
window that is missing them, and stores ``streams_payload`` (plus refreshes
splits / normalized power / max power from the streams).

It only READS from the Stryd API and WRITES ``streams_payload`` / ``splits`` /
``form_metrics`` on existing ``stryd_activities`` rows — it does not create
workouts or touch reconcile.

Usage::

    ENVIRONMENT=uat DATABASE_URL=$DATABASE_URL_UAT \
      python scripts/backfill_stryd_streams.py <username> [--days 183] [--dry-run]

Exit codes:
    0  — success (some activities may have failed individually; see summary)
    1  — fatal (user/credentials not found, bad args)
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import engine, environment
from backend.models import StrydActivity, User
from backend.services.stryd import refresh_stryd_session_if_needed
from backend.services.stryd_sync import (
    fetch_stryd_activity_streams,
    compute_km_splits,
    _normalized_power,
)


def _has_streams(activity) -> bool:
    sp = activity.streams_payload
    return isinstance(sp, dict) and bool(sp.get("timestamp_list"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    ap.add_argument("--days", type=int, default=183, help="look-back window (default 183 ≈ 6 months)")
    ap.add_argument("--sleep", type=float, default=0.4, help="seconds between Stryd API calls")
    ap.add_argument("--dry-run", action="store_true", help="list what would be backfilled, no writes/API")
    args = ap.parse_args()

    print(f"[env={environment}] backfill Stryd streams for '{args.username}', last {args.days} days")

    with Session(engine) as session:
        user = session.execute(
            select(User).where(User.name == args.username)
        ).scalar_one_or_none()
        if user is None:
            print(f"ERROR: user '{args.username}' not found", file=sys.stderr)
            sys.exit(1)
        uid = user.id

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=args.days)
        activities = session.execute(
            select(StrydActivity)
            .where(StrydActivity.user_id == uid, StrydActivity.start_time >= cutoff)
            .order_by(StrydActivity.start_time.desc())
        ).scalars().all()

        missing = [a for a in activities if not _has_streams(a)]
        ids = [a.stryd_activity_id for a in missing]

    print(f"  {len(activities)} Stryd activities in window; {len(missing)} missing streams")
    if not missing:
        print("  nothing to backfill.")
        return
    if args.dry_run:
        for a in missing:
            print(f"  would backfill {a.stryd_activity_id}  {a.start_time}  {a.name}")
        return

    token = refresh_stryd_session_if_needed(str(uid))
    if not token:
        print("ERROR: no valid Stryd session/credentials for this user", file=sys.stderr)
        sys.exit(1)

    ok = 0
    failed = 0
    for i, aid in enumerate(ids, 1):
        try:
            streams = fetch_stryd_activity_streams(token, aid)
            vals: dict = {}
            if streams.get("timestamp_list"):
                vals["streams_payload"] = streams
            splits = compute_km_splits(streams)
            if splits:
                vals["splits"] = splits
            powers = [x for x in (streams.get("total_power_list") or []) if isinstance(x, (int, float))]
            np = _normalized_power(powers)
            fm = {}
            if np is not None:
                fm["np_w"] = np
            if powers:
                fm["max_power_w"] = round(max(powers))
            if fm:
                vals["form_metrics"] = fm
            if vals:
                with Session(engine) as session:
                    session.query(StrydActivity).filter(
                        StrydActivity.stryd_activity_id == aid
                    ).update(vals, synchronize_session=False)
                    session.commit()
                ok += 1
                print(f"  [{i}/{len(ids)}] {aid} ✓ ({'streams' if 'streams_payload' in vals else 'no timestamps'})")
            else:
                print(f"  [{i}/{len(ids)}] {aid} — no usable streams returned")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [{i}/{len(ids)}] {aid} ✗ {exc}", file=sys.stderr)
        time.sleep(args.sleep)

    print(f"\nDone. backfilled={ok} failed={failed} of {len(ids)}")


if __name__ == "__main__":
    main()
