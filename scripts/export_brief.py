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

SCHEMA_VERSION = 3
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


# All-null weight block — returned whenever the worker's /api/weight/status
# is unreachable or errors, so a weight-tracking hiccup never takes down the
# whole brief export (unlike _fetch_plan, which is allowed to raise).
_NULL_WEIGHT_BLOCK: dict = {
    "current_kg": None,
    "trend_7d": None,
    "trend_28d": None,
    "target_kg": None,
    "target_date": None,
    "pace_kg_per_week": None,
    "on_track": None,
    "projection_date": None,
}


def _fetch_weight_status(worker_url: str, date_str: str, username: str | None) -> dict:
    """Fetch the weight block from the worker's /api/weight/status.

    Mirrors _fetch_plan's HTTP-call style (urllib, 10s timeout), but degrades
    to an all-null weight block on any network/parsing error instead of
    raising — the weight block is a nice-to-have addition to the brief, not
    load-bearing like today's/tomorrow's planned session.
    """
    url = f"{worker_url.rstrip('/')}/api/weight/status?date={date_str}"
    if username:
        url += f"&user={urllib.request.quote(username)}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return {**_NULL_WEIGHT_BLOCK, **data}
    except Exception as exc:
        print(f"WARNING: weight status unavailable: {exc}", file=sys.stderr)
        return dict(_NULL_WEIGHT_BLOCK)


def _assemble_weight(user_id: str, for_date: date, worker_url: str, username: str | None) -> dict:
    """Assemble the brief's top-level "weight" block.

    user_id is accepted for signature symmetry with the other _assemble_*
    functions in this module but isn't used directly here — like
    _fetch_plan, the worker resolves the target user itself from ?user=
    (falling back to WORKER_READ_API_USER / single-active-user).
    """
    return _fetch_weight_status(worker_url, for_date.isoformat(), username)


def _compute_weight_advisory(weight: dict, verdict: str | None) -> dict | None:
    """Rule-computed (no LLM/model calls) weight advisory, cross-referenced
    against the current training verdict/phase. Returns at most one advisory
    dict {key, severity, text}, or None.

    Decision table (training phase always wins over pace when they conflict):

    | target set? | on_track      | verdict == "build" (load-increasing) | advisory                                   |
    |-------------|---------------|---------------------------------------|---------------------------------------------|
    | no          | n/a           | n/a                                     | None — nothing to compare against            |
    | yes         | None (n/a)    | n/a                                     | None — insufficient weigh-in data to judge   |
    | yes         | True or False | True                                    | HOLD intake (build/race-week block; never a deficit push) |
    | yes         | False         | False (hold/back_off/unknown)          | encourage tightening up (no load conflict)   |
    | yes         | True          | False (hold/back_off/unknown)          | None — on pace and no conflict; nothing to flag |

    The core invariant: a "build" verdict NEVER produces a deficit-push
    recommendation, regardless of pace — it always recommends holding intake
    instead. An unknown verdict (None, e.g. training-load data unavailable)
    is treated the same as a non-build verdict — there's no known conflict to
    guard against, so pace alone drives the (possibly absent) advisory.
    """
    if not weight or weight.get("target_kg") is None:
        return None

    on_track = weight.get("on_track")
    if on_track is None:
        return None

    if verdict == "build":
        if on_track:
            text = (
                "You're on pace toward your weight target, but you're entering "
                "a build block — hold intake here rather than pushing the "
                "deficit further."
            )
        else:
            text = (
                "You're behind pace on your weight target, but you're entering "
                "a build block — hold intake here rather than adding a deficit "
                "on top of rising training load. Tighten up once the block eases."
            )
        return {"key": "weight_hold_intake_build", "severity": "info", "text": text}

    if on_track is False:
        return {
            "key": "weight_pace_behind_tighten_up",
            "severity": "warn",
            "text": (
                "Pace is behind your weight target and training load isn't "
                "ramping — tighten up intake this week."
            ),
        }

    # on_track is True and verdict isn't load-increasing: things are fine.
    return None


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


def _assemble_advisories(user_id: str, for_date: date, weight: dict) -> list[dict]:
    """Map gap-analysis findings + training verdict (+ weight status) to advisory objects."""
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

    # Verdict fetched once here (rather than inside its own try/except only)
    # so the weight advisory below — which must cross-reference the current
    # training phase — can share the exact same value. None when unavailable.
    verdict_str: str | None = None
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

    # Weight advisory: rule-computed, cross-referenced against the training
    # verdict above so it never recommends a deficit push during a build
    # block (see _compute_weight_advisory's decision table).
    try:
        weight_advisory = _compute_weight_advisory(weight, verdict_str)
        if weight_advisory is not None:
            advisories.append(weight_advisory)
    except Exception as exc:
        print(f"WARNING: weight advisory computation failed: {exc}", file=sys.stderr)

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


def _load_goal_for_user(user_id: str):
    """Return the active PerformanceGoal for user_id, or None."""
    from sqlalchemy.orm import Session

    from backend.db import engine
    from backend.models import PerformanceGoal

    with Session(engine) as db:
        return (
            db.query(PerformanceGoal)
            .filter(
                PerformanceGoal.user_id == user_id,
                PerformanceGoal.active.is_(True),
            )
            .first()
        )


def _build_plan_state_for_user(goal, for_date: date) -> tuple:
    """Build (plan_state, projection_info) from an active goal.

    Returns a 2-tuple: (plan_state dict, projection_info dict).
    Delegates entirely to the weekly_coach_message service helpers so the
    brief and the weekly message share the same computation.
    """
    from backend.services.weekly_coach_message import (
        _build_projection_info,
        _load_inputs_for_user,
    )
    from backend.services.coach_plan import build_plan_state
    from sqlalchemy.orm import Session

    from backend.db import engine

    with Session(engine) as db:
        _, snapshot, weight_status, log_consistency = _load_inputs_for_user(
            goal.user_id, db, for_date
        )

    acwr_val = float(getattr(snapshot, "acwr", 0) or 0) if snapshot else 0.0
    acwr_state = "high_risk" if acwr_val > 1.30 else "productive"

    plan_state = build_plan_state(
        goal=goal,
        training_load_snapshot=snapshot,
        acwr_state=acwr_state,
        guardrail_state="ok",
        weight_status=weight_status or {"current_kg": None, "goal_kg": None, "gap_kg": 0.0},
        log_consistency=log_consistency or {"logged_days": 0, "total_days": 14},
        _today=for_date,
    )
    projection_info = _build_projection_info(goal, snapshot, for_date)
    return plan_state, projection_info


def _coach_lever_strings(levers: dict) -> list[str]:
    """Compact pill text for each lever."""
    result: list[str] = []

    load = levers.get("load") or {}
    load_state = load.get("state", "unavailable")
    if load_state == "locked":
        unlock_date = load.get("unlock_date")
        if unlock_date and isinstance(unlock_date, date):
            date_str = unlock_date.strftime("%-d %b")
        else:
            date_str = "soon"
        result.append(f"load: locked until {date_str}")
    elif load_state == "available":
        result.append("load: available to ramp")
    else:
        result.append("load: unavailable")

    weight = levers.get("weight") or {}
    logged = weight.get("logged_days")
    total = weight.get("total_days", 14)
    if logged is not None:
        result.append(f"weight: measurement {logged}/{total} days")
    else:
        result.append("weight: no data")

    return result


def _assemble_coach(user_id: str, for_date: date) -> dict | None:
    """Assemble the coach block for the daily brief.

    Returns a dict with directive (str), projection (str), and levers (list[str])
    when an active goal exists, or None when no active goal is set.

    Never raises — any internal failure degrades to None so the brief export
    continues without the coach block.
    """
    try:
        goal = _load_goal_for_user(user_id)
        if goal is None:
            return None

        plan_state, projection_info = _build_plan_state_for_user(goal, for_date)

        from backend.services.weekly_coach_message import compose_deterministic_message
        full_message = compose_deterministic_message(plan_state, projection_info, for_date)

        # Extract the "Now:" sentence (first paragraph of the message) as directive.
        paragraphs = [p.strip() for p in full_message.split("\n\n") if p.strip()]
        directive = paragraphs[0] if paragraphs else full_message

        # Build a compact one-line projection from the last paragraph ("Projection:").
        projection_para = next(
            (p for p in paragraphs if p.startswith("Projection:")), None
        )
        if projection_para:
            projection = projection_para[len("Projection:"):].strip()
        else:
            from backend.services.weekly_coach_message import (
                _format_hms,
            )
            if projection_info:
                full_t = _format_hms(projection_info.get("full_compliance_time_seconds", 0))
                trend_t = _format_hms(projection_info.get("current_trend_time_seconds", 0))
                label = projection_info.get("distance_label", "race")
                target_dt = projection_info.get("target_date")
                month = target_dt.strftime("%b") if target_dt else "race day"
                projection = f"plan → ~{full_t} {label} by {month} · now ~{trend_t}"
            else:
                projection = "No projection available"

        levers = _coach_lever_strings((plan_state.get("levers") or {}))

        return {
            "directive": directive,
            "projection": projection,
            "levers": levers,
        }
    except Exception as exc:
        print(f"WARNING: coach block unavailable: {exc}", file=sys.stderr)
        return None


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
    weight = _assemble_weight(user_id, for_date, worker_url, username)
    advisories = _assemble_advisories(user_id, for_date, weight)
    coach = _assemble_coach(user_id, for_date)

    generated_at = datetime.now(BANGKOK_TZ).isoformat()

    payload: dict = {
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
    }
    if coach is not None:
        payload["coach"] = coach
    return payload


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
