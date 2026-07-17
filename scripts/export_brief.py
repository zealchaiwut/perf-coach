#!/usr/bin/env python3
"""Export Hermes coaching brief to perfcoach_brief.latest.json.

Thin CLI wrapper — all assembly logic lives in backend.services.daily_brief.
Acquires a file lock, calls _build_brief(), and writes the result atomically.

Usage:
    python scripts/export_brief.py [--date YYYY-MM-DD] [--dry-run]
        [--env uat|prd] [--user USERNAME] [--output PATH]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# All assembly logic lives in the service.  Helper names are re-imported into
# this module's namespace so that existing test patches such as
#   patch.object(m, "_assemble_form", fake_form)
# continue to work: _build_brief below looks up these names from this module's
# globals, so patching them here takes effect.
from backend.services.daily_brief import (  # noqa: F401
    SCHEMA_VERSION,
    BANGKOK_TZ,
    DEFAULT_WINDOW_DAYS,
    _NULL_WEIGHT_BLOCK,
    _assemble_form,
    _assemble_weight,
    _assemble_advisories,
    _assemble_recent_wrap,
    _assemble_week_plan,
    _compute_weight_advisory,
    _load_interpretation,
    _plan_to_session,
    _get_plan_for_date,
    build_brief,
)

WORKER_DEFAULT_URL = "http://127.0.0.1:9100"


def _today_bkk() -> date:
    return datetime.now(BANGKOK_TZ).date()


def _fetch_plan(worker_url: str, date_str: str, user_id: str | None) -> dict:
    """Bridge to the service's direct DB query.

    Previously this made an HTTP call to the worker's /api/plan/today; it now
    queries PlannedSession directly so the script works without the worker process
    running.  The function signature is preserved so existing test patches
    (patch.object(m, "_fetch_plan", ...)) intercept calls from _build_brief.
    worker_url is accepted but ignored.
    """
    for_date = date.fromisoformat(date_str)
    return _get_plan_for_date(user_id, for_date)


def _build_brief(for_date: date, worker_url=None, user_id=None, username=None) -> dict:
    """Assemble and return the complete brief payload.

    Defined in this module (in addition to the service) so that
    patch.object(m, "_assemble_form", ...) / patch.object(m, "_fetch_plan", ...)
    in existing tests affect the lookups inside this function.
    worker_url and username are accepted for backward compatibility; they are not used.
    """
    tomorrow = for_date + timedelta(days=1)

    today_plan = _fetch_plan(worker_url or "", for_date.isoformat(), user_id)
    tomorrow_plan = _fetch_plan(worker_url or "", tomorrow.isoformat(), user_id)

    today_session = _plan_to_session(today_plan, for_date)
    tomorrow_session = _plan_to_session(tomorrow_plan, tomorrow)

    form = _assemble_form(user_id, for_date)
    recent_wrap = _assemble_recent_wrap(user_id, for_date)
    weight = _assemble_weight(user_id, for_date)
    advisories = _assemble_advisories(user_id, for_date, weight)
    week_plan = _assemble_week_plan(user_id, for_date)

    generated_at = datetime.now(BANGKOK_TZ).isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "for_date": for_date.isoformat(),
        "generated_at": generated_at,
        "today": today_session,
        "tomorrow": tomorrow_session,
        "form": form,
        "recent_wrap": recent_wrap,
        "weight": weight,
        "advisories": advisories,
        "actions": [],
        "week_plan": week_plan,
    }


def _write_atomic(path: str, data: dict) -> None:
    """Serialise data to a tempfile in the same directory, then os.replace."""
    dir_path = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _resolve_user(username: str | None) -> str:
    from sqlalchemy import text

    from backend.db import engine

    with engine.connect() as conn:
        if username:
            row = conn.execute(
                text("SELECT id FROM users WHERE name = :n AND is_active = TRUE"),
                {"n": username},
            ).first()
            if row is None:
                raise RuntimeError(f"User {username!r} not found or inactive")
            return str(row[0])

        rows = conn.execute(
            text("SELECT id FROM users WHERE is_active = TRUE")
        ).fetchall()
        if len(rows) == 1:
            return str(rows[0][0])
        if not rows:
            raise RuntimeError("No active users found in database")
        raise RuntimeError(
            "Multiple active users found — pass --user to specify one"
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export Hermes coaching brief to perfcoach_brief.latest.json",
    )
    ap.add_argument("--date", default=None, help="Date for the brief (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print JSON to stdout only — do not write file or acquire lock")
    ap.add_argument("--env", default="uat", choices=["uat", "prd"],
                    help="Database environment (default: uat)")
    ap.add_argument("--user", default=None,
                    help="Username to generate brief for (default: single active user)")
    ap.add_argument("--output", default=None,
                    help="Output file path (default: perfcoach_brief.latest.json next to the script)")
    ap.add_argument("--worker-url", default=None, dest="worker_url",
                    help=f"Ignored — kept for backward compatibility (default: {WORKER_DEFAULT_URL})")
    args = ap.parse_args()

    if args.date:
        try:
            for_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
            return 1
    else:
        for_date = _today_bkk()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = args.output or os.path.join(script_dir, "perfcoach_brief.latest.json")
    lock_path = os.path.join(os.path.dirname(os.path.abspath(output_path)), "perfcoach_brief.lock")
    worker_url = args.worker_url or os.getenv("WORKER_BASE_URL") or WORKER_DEFAULT_URL

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    url_key = f"DATABASE_URL_{args.env.upper()}"
    if not os.getenv("DATABASE_URL"):
        env_url = os.getenv(url_key)
        if not env_url:
            print(
                f"ERROR: {url_key} or DATABASE_URL must be set in the environment or .env file",
                file=sys.stderr,
            )
            return 1
        os.environ["DATABASE_URL"] = env_url

    os.environ.setdefault("ENVIRONMENT", args.env)

    try:
        user_id = _resolve_user(args.user)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        try:
            brief = _build_brief(for_date, worker_url, user_id, args.user)
            print(json.dumps(brief, indent=2))
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    lock_fd = None
    try:
        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(
                f"ERROR: another export is already running (lock held at {lock_path})",
                file=sys.stderr,
            )
            return 1

        brief = _build_brief(for_date, worker_url, user_id, args.user)
        _write_atomic(output_path, brief)
        print(f"Brief written to {output_path}", file=sys.stderr)
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
