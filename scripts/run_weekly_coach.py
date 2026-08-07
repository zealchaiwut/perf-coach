"""Generate and persist weekly coaching messages for all active users (issue #1504).

Usage:
    python scripts/run_weekly_coach.py [--user-id UUID] [--date YYYY-MM-DD]

Options:
    --user-id UUID     Process only this user (UUID).  Omit to process all active users.
    --date YYYY-MM-DD  Override today's date for the generation (for testing/backfill).

Exit codes:
    0 — all users processed successfully
    1 — one or more users failed (error messages printed to stderr)

Environment:
    ENVIRONMENT, DATABASE_URL / DATABASE_URL_UAT / DATABASE_URL_PRD must be set.
    Load from .env via `source .env` or set in the environment before running.
    Warmth rephrase uses LLM_COACH_ENABLED + provider API keys (see .env.example).
    Prefer triggering via POST /internal/daily-coach/run on zeal-server in
    production; this CLI is for local/ops backfill.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate weekly coaching messages for active users."
    )
    parser.add_argument("--user-id", dest="user_id", default=None, help="Process a single user by UUID.")
    parser.add_argument("--date", dest="as_of_date", default=None, help="Override today's date (YYYY-MM-DD).")
    return parser.parse_args()


def _load_env() -> None:
    """Load .env if present and DATABASE_URL is not already set."""
    import os
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    if env_file.exists() and not os.getenv("DATABASE_URL"):
        try:
            from dotenv import dotenv_values
            vals = dotenv_values(env_file)
            for k, v in vals.items():
                os.environ.setdefault(k, v or "")
        except ImportError:
            pass


def _all_active_user_ids(db) -> list:
    from backend.models import User
    rows = db.query(User.id).filter_by(is_active=True).all()
    return [r[0] for r in rows]


def main() -> int:
    _load_env()

    args = _parse_args()

    today: date
    if args.as_of_date:
        today = date.fromisoformat(args.as_of_date)
    else:
        today = date.today()

    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.services.weekly_coach_message import generate_for_user

    errors: list[str] = []

    with Session(engine) as db:
        if args.user_id:
            import uuid
            user_ids = [uuid.UUID(args.user_id)]
        else:
            user_ids = _all_active_user_ids(db)

    if not user_ids:
        print("No active users found.", file=sys.stderr)
        return 0

    print(f"Generating weekly messages for {len(user_ids)} user(s) — week of {today}...")

    for uid in user_ids:
        try:
            result = generate_for_user(user_id=uid, today=today)
            if result is None:
                print(f"  [skip] {uid} — no active goal")
            else:
                print(f"  [ok]   {uid} — {result['for_week']} persisted")
        except Exception as exc:
            msg = f"  [err]  {uid} — {exc}"
            print(msg, file=sys.stderr)
            errors.append(msg)

    if errors:
        print(f"\n{len(errors)} error(s) encountered.", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
