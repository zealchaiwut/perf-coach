#!/usr/bin/env python3
"""Run a Strava activity sync for a given user.

Pulls Strava activities into the strava_activities cache by calling
sync_strava_activities(). Logs start, progress, and completion to stdout.

Usage:
    python scripts/run_strava_sync.py [--user_id UUID] [--env uat|prd]

If --user_id is omitted, the script falls back to the first active user
that has a connected Strava token in the target environment.

Exit codes:
    0 — sync completed successfully
    1 — sync failed or user could not be resolved
"""

import argparse
import os
import sys
import uuid as _uuid_mod


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a Strava activity sync. "
            "Pass --user_id to target a specific user; "
            "omit it to fall back to the first user with a connected Strava token."
        )
    )
    parser.add_argument(
        "--user_id",
        default=None,
        help="UUID of the user to sync (default: first user with a Strava token)",
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


def _resolve_user_id(user_id_arg: str | None, engine) -> str:
    """Return a resolved user_id string.

    If user_id_arg is provided, validates it as a UUID.
    Otherwise falls back to the first user with an active Strava token.
    """
    if user_id_arg is not None:
        try:
            _uuid_mod.UUID(user_id_arg)
        except ValueError:
            raise ValueError(f"--user_id '{user_id_arg}' is not a valid UUID")
        return user_id_arg

    from sqlalchemy import select, text
    from sqlalchemy.orm import Session

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend.models import StravaToken

    with Session(engine) as session:
        row = session.execute(
            select(StravaToken.user_id)
            .order_by(StravaToken.updated_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    if row is None:
        raise RuntimeError(
            "No Strava tokens found. Connect a Strava account first, "
            "or pass --user_id explicitly."
        )
    return str(row)


def main() -> int:
    args = _parse_args()

    # Bootstrap sys.path so backend imports work when run from repo root.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from dotenv import load_dotenv
    load_dotenv()

    env = args.env
    os.environ.setdefault("ENVIRONMENT", env)
    url_key = f"DATABASE_URL_{env.upper()}"
    db_url = os.getenv(url_key)
    if db_url:
        os.environ.setdefault("DATABASE_URL", db_url)

    try:
        engine = _build_engine(env)
    except RuntimeError as exc:
        print(f"[run_strava_sync] ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        user_id = _resolve_user_id(args.user_id, engine)
    except (ValueError, RuntimeError) as exc:
        print(f"[run_strava_sync] ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[run_strava_sync] Starting Strava sync for user {user_id} (env={env})")

    try:
        from backend.services.strava_sync import sync_strava_activities
        result = sync_strava_activities(user_id=user_id)
    except Exception as exc:
        print(f"[run_strava_sync] FAILED: {exc}", file=sys.stderr)
        return 1

    created = result.get("activities_created", 0)
    updated = result.get("activities_updated", 0)
    skipped = result.get("activities_skipped", 0)
    status = result.get("status", "unknown")

    print(
        f"[run_strava_sync] Done — status={status} "
        f"created={created} updated={updated} skipped={skipped}"
    )

    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
