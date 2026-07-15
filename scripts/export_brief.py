#!/usr/bin/env python3
"""Export Hermes coaching brief to perfcoach_brief.latest.json.

Aggregates today/tomorrow sessions, form metrics, recent adherence, and
advisories into a versioned JSON snapshot written atomically so readers
never see a partial file.

Usage:
    python scripts/export_brief.py [--date YYYY-MM-DD] [--dry-run]
        [--env uat|prd] [--user USERNAME] [--output PATH] [--worker-url URL]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
DEFAULT_WINDOW_DAYS = 14
WORKER_DEFAULT_URL = "http://127.0.0.1:9100"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today_bkk() -> date:
    return datetime.now(BANGKOK_TZ).date()


def _load_interpretation(ctl: float, atl: float, tsb: float) -> str:
    """Mirror of main.py _load_interpretation (TSB interpretation spec #259)."""
    if tsb >= 5:
        label = "Fresh"
    elif tsb >= -5:
        label = "Neutral"
    elif tsb >= -15:
        label = "Productive (high load)"
    else:
        label = "Overreached (high risk)"

    if ctl > 60:
        return f"{label}, well-trained"
    if ctl < 30:
        return f"{label}, undertrained"
    return label


# ── Data assembly ─────────────────────────────────────────────────────────────

def _fetch_plan(worker_url: str, date_str: str, username: str | None) -> dict:
    """Fetch planned sessions for date_str from the worker /api/plan/today."""
    url = f"{worker_url.rstrip('/')}/api/plan/today?date={date_str}"
    if username:
        url += f"&user={urllib.request.quote(username)}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Worker unreachable at {worker_url}: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch plan for {date_str}: {exc}") from exc


def _plan_to_session(plan_resp: dict, for_date: date) -> dict:
    """Convert a /api/plan/today response into a brief session object."""
    sessions = plan_resp.get("sessions") or []
    planned = plan_resp.get("planned", False)

    if sessions:
        s = sessions[0]
        target = s.get("target") or {}
        return {
            "date": for_date.isoformat(),
            "session_type": s.get("session_type"),
            "planned": planned,
            "intensity": target.get("intensity"),
            "duration_min": target.get("duration_min"),
            "notes": s.get("note"),
        }

    return {
        "date": for_date.isoformat(),
        "session_type": None,
        "planned": planned,
        "intensity": None,
        "duration_min": None,
        "notes": None,
    }


def _assemble_form(user_id: str, for_date: date) -> dict:
    """Assemble form metrics from training_load_snapshots + guardrail."""
    from backend.services.guardrail import get_guardrail_result
    from backend.services.training_load import current_load, get_snapshot_series

    load = current_load(user_id, as_of=for_date)
    ctl = round(float(load["ctl"]), 2)
    atl = round(float(load["atl"]), 2)
    tsb = round(float(load["tsb"]), 2)

    # Ramp = CTL change over the past 7 days (positive → load building)
    past_date = for_date - timedelta(days=7)
    series = get_snapshot_series(user_id, past_date, for_date)
    if len(series) >= 2:
        ramp = round(float(series[-1]["ctl"]) - float(series[0]["ctl"]), 2)
    else:
        ramp = 0.0

    guardrail = get_guardrail_result(user_id, as_of_date=for_date)
    flags = {
        "guardrail_state": guardrail.get("guardrail_state"),
        "acwr_state": guardrail.get("acwr_state"),
        "stressors_ramping": guardrail.get("stressors_ramping"),
    }

    return {
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "ramp": ramp,
        "flags": flags,
        "interpretation": _load_interpretation(ctl, atl, tsb),
    }


def _assemble_recent_wrap(
    user_id: str,
    for_date: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    """Assemble planned-session adherence + load trend + weekly highlights."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.services.training_load import current_load

    window_start = for_date - timedelta(days=window_days - 1)

    with Session(engine) as s:
        rows = s.execute(
            text(
                "SELECT status FROM planned_sessions "
                "WHERE user_id = :uid "
                "  AND planned_date BETWEEN :start AND :end"
            ),
            {"uid": str(user_id), "start": window_start, "end": for_date},
        ).fetchall()

    sessions_planned = len(rows)
    done_statuses = {"done_auto", "done_manual"}
    sessions_completed = sum(1 for r in rows if r[0] in done_statuses)
    adherence = sessions_completed / sessions_planned if sessions_planned > 0 else 0.0

    # Load trend: CTL change over the past 7 days
    prev_week_date = for_date - timedelta(days=7)
    curr_load = current_load(user_id, as_of=for_date)
    prev_load = current_load(user_id, as_of=prev_week_date)
    load_trend = round(float(curr_load["ctl"]) - float(prev_load["ctl"]), 2)

    highlights_md = _build_highlights_md(user_id, for_date)

    return {
        "window_days": window_days,
        "sessions_planned": sessions_planned,
        "sessions_completed": sessions_completed,
        "adherence": round(adherence, 3),
        "load_trend": load_trend,
        "highlights_md": highlights_md,
    }


def _build_highlights_md(user_id: str, for_date: date) -> str:
    """Build a weekly narrative via the weekly_summary service."""
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.models import Workout
    from backend.services.guardrail import get_guardrail_result
    from backend.services.training_load import current_load
    from backend.services.training_verdict import compute_verdict
    from backend.services.weekly_summary import assemble_facts, build_fallback_narrative

    week_start = for_date - timedelta(days=for_date.weekday())
    week_end = for_date
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)

    def _w_dict(w) -> dict:
        return {
            "workout_date": w.workout_date.isoformat() if w.workout_date else None,
            "tss": float(w.tss) if w.tss is not None else None,
            "distance_km": float(w.distance_km) if w.distance_km is not None else None,
            "duration_seconds": w.duration_seconds,
            "workout_type": w.workout_type or "",
        }

    with Session(engine) as s:
        import uuid as _uuid

        uid = _uuid.UUID(str(user_id))
        curr_workouts = [_w_dict(w) for w in s.query(Workout).filter(
            Workout.user_id == uid,
            Workout.workout_date >= week_start,
            Workout.workout_date <= week_end,
        ).all()]
        prev_workouts = [_w_dict(w) for w in s.query(Workout).filter(
            Workout.user_id == uid,
            Workout.workout_date >= prev_week_start,
            Workout.workout_date <= prev_week_end,
        ).all()]

    load_start = current_load(user_id, as_of=prev_week_end)
    load_end = current_load(user_id, as_of=week_end)
    guardrail = get_guardrail_result(user_id, as_of_date=week_end)
    snap = {
        "ctl": load_end["ctl"],
        "atl": load_end["atl"],
        "tsb": load_end["tsb"],
        "acwr": load_end.get("acwr"),
    }
    verdict = compute_verdict(snap)

    facts = assemble_facts(
        week_start=week_start,
        current_workouts=curr_workouts,
        prev_workouts=prev_workouts,
        prs=[],
        ctl_start=float(load_start["ctl"]),
        ctl_end=float(load_end["ctl"]),
        atl_start=float(load_start["atl"]),
        atl_end=float(load_end["atl"]),
        tsb_start=float(load_start["tsb"]),
        tsb_end=float(load_end["tsb"]),
        guardrail=guardrail,
        verdict=dict(verdict),
    )
    return build_fallback_narrative(facts)


def _assemble_advisories(user_id: str, for_date: date) -> list[dict]:
    """Map gap-analysis findings + training verdict to advisory objects."""
    import uuid as _uuid

    advisories: list[dict] = []

    try:
        from sqlalchemy.orm import Session

        from backend.db import engine
        from backend.services.gap_analysis.engine import run_gap_analysis

        uid = _uuid.UUID(str(user_id))
        with Session(engine) as db:
            result = run_gap_analysis(db, uid, for_date)

        for f in result.get("findings", []):
            severity_int = f.get("severity", 1)
            severity = "warn" if severity_int >= 2 else "info"
            advisories.append({
                "key": f.get("code", ""),
                "severity": severity,
                "text": f.get("recommendation", ""),
            })
    except Exception as exc:
        print(f"WARNING: gap analysis unavailable: {exc}", file=sys.stderr)

    # Append verdict advisory for non-build verdicts
    try:
        from backend.services.gap_analysis.engine import _gather_training_verdict

        uid = _uuid.UUID(str(user_id))
        verdict_str = _gather_training_verdict(uid, for_date)
        if verdict_str and verdict_str != "build":
            advisories.append({
                "key": f"verdict_{verdict_str}",
                "severity": "warn",
                "text": f"Training verdict: {verdict_str.replace('_', ' ')}. Adjust load accordingly.",
            })
    except Exception as exc:
        print(f"WARNING: training verdict unavailable: {exc}", file=sys.stderr)

    return advisories


def _resolve_user(username: str | None) -> str:
    """Return a user ID string for the given username or single active user."""
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


def _build_brief(
    for_date: date,
    worker_url: str,
    user_id: str,
    username: str | None,
) -> dict:
    """Assemble and return the complete brief payload."""
    tomorrow = for_date + timedelta(days=1)

    today_plan = _fetch_plan(worker_url, for_date.isoformat(), username)
    tomorrow_plan = _fetch_plan(worker_url, tomorrow.isoformat(), username)

    today_session = _plan_to_session(today_plan, for_date)
    tomorrow_session = _plan_to_session(tomorrow_plan, tomorrow)

    form = _assemble_form(user_id, for_date)
    recent_wrap = _assemble_recent_wrap(user_id, for_date)
    advisories = _assemble_advisories(user_id, for_date)

    generated_at = datetime.now(BANGKOK_TZ).isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "for_date": for_date.isoformat(),
        "generated_at": generated_at,
        "today": today_session,
        "tomorrow": tomorrow_session,
        "form": form,
        "recent_wrap": recent_wrap,
        "advisories": advisories,
        "actions": [],
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


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export Hermes coaching brief to perfcoach_brief.latest.json",
    )
    ap.add_argument(
        "--date",
        default=None,
        help="Date for the brief (YYYY-MM-DD, default: today in +07:00)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON to stdout only — do not write file or acquire lock",
    )
    ap.add_argument(
        "--env",
        default="uat",
        choices=["uat", "prd"],
        help="Database environment (default: uat)",
    )
    ap.add_argument(
        "--user",
        default=None,
        help="Username to generate brief for (default: single active user)",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="Output file path (default: perfcoach_brief.latest.json next to the script)",
    )
    ap.add_argument(
        "--worker-url",
        default=None,
        dest="worker_url",
        help=f"Worker base URL (default: WORKER_BASE_URL env or {WORKER_DEFAULT_URL})",
    )
    args = ap.parse_args()

    # Resolve for_date
    if args.date:
        try:
            for_date = date.fromisoformat(args.date)
        except ValueError:
            print(
                f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}",
                file=sys.stderr,
            )
            return 1
    else:
        for_date = _today_bkk()

    # Resolve paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = args.output or os.path.join(script_dir, "perfcoach_brief.latest.json")
    lock_path = os.path.join(os.path.dirname(os.path.abspath(output_path)), "perfcoach_brief.lock")

    # Resolve worker URL
    worker_url = args.worker_url or os.getenv("WORKER_BASE_URL") or WORKER_DEFAULT_URL

    # Bootstrap DB environment (must happen before any backend imports)
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

    # Resolve user
    try:
        user_id = _resolve_user(args.user)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # --dry-run: build + print, no I/O side effects
    if args.dry_run:
        try:
            brief = _build_brief(for_date, worker_url, user_id, args.user)
            print(json.dumps(brief, indent=2))
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Normal mode: acquire lock, build, write atomically
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
