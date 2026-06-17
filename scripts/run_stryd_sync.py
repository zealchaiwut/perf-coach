"""Run a Stryd sync from the CLI, or inspect the raw Stryd API response.

    ENVIRONMENT=uat DATABASE_URL="$DATABASE_URL_UAT" PYTHONPATH=. \
      .venv/bin/python scripts/run_stryd_sync.py --user_id <UUID> [--since YYYY-MM-DD]

    # Dump the raw API shape to verify field names:
      ... scripts/run_stryd_sync.py --user_id <UUID> --inspect
"""
import argparse
import json
from datetime import date

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import StrydCredentials
from backend.services.stryd import refresh_stryd_session_if_needed
from backend.services import stryd_sync


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_id", required=True)
    ap.add_argument("--since", help="YYYY-MM-DD")
    ap.add_argument("--inspect", action="store_true", help="Dump raw API response, do not write")
    args = ap.parse_args()

    since = date.fromisoformat(args.since) if args.since else None

    if args.inspect:
        token = refresh_stryd_session_if_needed(args.user_id)
        with Session(engine) as s:
            cred = s.query(StrydCredentials).filter(StrydCredentials.user_id == args.user_id).one()
            athlete_id = cred.athlete_id
        raw = stryd_sync.fetch_stryd_activities(token, athlete_id, since_date=since)
        print(f"fetched {len(raw)} activities")
        if raw:
            print("=== FIRST RAW ACTIVITY (keys) ===")
            print(sorted(raw[0].keys()))
            print("=== MAPPED ===")
            print(json.dumps(stryd_sync.map_stryd_activity(raw[0], args.user_id), indent=2, default=str))
        return

    result = stryd_sync.sync_stryd_activities(args.user_id, since_date=since)
    print(f"fetched={result['fetched']} created={result['created']} updated={result['updated']}")


if __name__ == "__main__":
    main()
