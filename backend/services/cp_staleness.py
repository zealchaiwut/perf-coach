"""Critical Power (CP) staleness check and confirmed-update flow (#1877).

Deterministic, no LLM. CP on file is ``user_preferences.ftp_w`` (+ ``ftp_w_source``,
``ftp_w_updated_at``); every confirmed change also appends a ``cp_history`` row.
Nothing here ever changes CP on its own — ``apply_cp_update`` only runs when the
athlete confirms via the API.

Staleness rules (runs in the last 6 weeks, average power over the whole run):
  * avg power >= 0.95 x CP for >= 60 min  -> stale
  * avg power >= 1.05 x CP for >= 20 min  -> stale
  * CP not updated for 6 weeks            -> stale (age rule)

Suggested CP from a qualifying effort:
  * 60-150 min: avg_power / 0.93 (rounded)
  * 20-60 min:  avg_power / 1.0  (rounded)
  * > 150 min:  can flag stale but is not used to suggest (fatigue-limited,
    the 0.93 factor no longer holds)
The suggestion is the highest candidate across qualifying efforts and is only
offered when it exceeds the CP on file.

See docs/calculations/cp-staleness.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

WINDOW_DAYS = 42
CP_MAX_AGE_DAYS = 42

LONG_EFFORT_MIN_S = 60 * 60
LONG_EFFORT_FRACTION = 0.95
SHORT_EFFORT_MIN_S = 20 * 60
SHORT_EFFORT_FRACTION = 1.05
SUGGEST_MAX_S = 150 * 60
LONG_SUGGEST_DIVISOR = 0.93
SHORT_SUGGEST_DIVISOR = 1.0

CP_MIN_W = 50
CP_MAX_W = 600
VALID_SOURCES = ("suggested", "stryd", "manual")


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _effort_trigger(avg_power: float, duration_s: int, cp_w: float) -> Optional[str]:
    """Return which staleness rule an effort trips, or None."""
    if duration_s >= LONG_EFFORT_MIN_S and avg_power >= LONG_EFFORT_FRACTION * cp_w:
        return "long_effort"
    if duration_s >= SHORT_EFFORT_MIN_S and avg_power >= SHORT_EFFORT_FRACTION * cp_w:
        return "short_effort"
    return None


def _suggest_from_effort(avg_power: float, duration_s: int) -> Optional[int]:
    if duration_s > SUGGEST_MAX_S or duration_s < SHORT_EFFORT_MIN_S:
        return None
    divisor = LONG_SUGGEST_DIVISOR if duration_s >= LONG_EFFORT_MIN_S else SHORT_SUGGEST_DIVISOR
    return int(round(avg_power / divisor))


def evaluate_cp_staleness(
    runs: Iterable[dict],
    current_cp_w: Optional[int],
    cp_updated_at: Optional[datetime],
    today: date,
    stryd_cp_w: Optional[int] = None,
) -> dict:
    """Pure staleness evaluation.

    ``runs``: dicts with ``date``, ``avg_power_w``, ``duration_seconds`` and
    optionally ``workout_id`` / ``name``. Runs outside the 6-week window or
    without power are ignored.
    """
    cutoff = today - timedelta(days=WINDOW_DAYS)
    result: dict = {
        "current_cp_w": current_cp_w,
        "cp_updated_at": cp_updated_at.isoformat() if cp_updated_at else None,
        "stale": False,
        "reasons": [],
        "triggering_efforts": [],
        "suggested_cp_w": None,
        "suggestion_basis": None,
        "stryd_cp_w": stryd_cp_w,
        "never_auto_updated": True,
    }
    if not current_cp_w:
        result["status"] = "no_cp"
        return result

    triggers = []
    best_candidate: Optional[int] = None
    best_effort: Optional[dict] = None
    for run in runs:
        d = _as_date(run.get("date"))
        power = run.get("avg_power_w")
        dur = run.get("duration_seconds")
        if d is None or not power or not dur or d < cutoff or d > today:
            continue
        rule = _effort_trigger(float(power), int(dur), float(current_cp_w))
        if rule is None:
            continue
        candidate = _suggest_from_effort(float(power), int(dur))
        effort = {
            "workout_id": run.get("workout_id"),
            "name": run.get("name"),
            "date": d.isoformat(),
            "avg_power_w": int(power),
            "duration_seconds": int(dur),
            "rule": rule,
            "suggested_cp_w": candidate,
        }
        triggers.append(effort)
        if candidate is not None and (best_candidate is None or candidate > best_candidate):
            best_candidate, best_effort = candidate, effort

    if triggers:
        result["reasons"].append("recent_effort_above_cp")
        result["triggering_efforts"] = sorted(triggers, key=lambda e: e["date"], reverse=True)
    updated_d = _as_date(cp_updated_at)
    if updated_d is None or (today - updated_d).days >= CP_MAX_AGE_DAYS:
        result["reasons"].append("cp_not_updated_6_weeks")

    result["stale"] = bool(result["reasons"])
    result["status"] = "stale" if result["stale"] else "fresh"
    if best_candidate is not None and best_candidate > current_cp_w:
        result["suggested_cp_w"] = best_candidate
        result["suggestion_basis"] = best_effort
    return result


# ── DB wrappers ──────────────────────────────────────────────────────────────

def load_recent_runs(session, user_id, today: date) -> list[dict]:
    from backend.models import Workout

    rows = (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type == "run",
            Workout.workout_date >= today - timedelta(days=WINDOW_DAYS),
            Workout.avg_power.isnot(None),
            Workout.duration_seconds.isnot(None),
        )
        .all()
    )
    return [
        {
            "workout_id": str(w.id),
            "name": w.name,
            "date": w.workout_date,
            "avg_power_w": w.avg_power,
            "duration_seconds": w.duration_seconds,
        }
        for w in rows
    ]


def latest_stryd_cp(session, user_id) -> Optional[int]:
    """Critical power from the most recent Stryd activity carrying power zones."""
    from sqlalchemy import desc

    from backend.models import StrydActivity

    latest = (
        session.query(StrydActivity)
        .filter(StrydActivity.user_id == user_id, StrydActivity.power_zones.isnot(None))
        .order_by(desc(StrydActivity.start_time))
        .first()
    )
    cp = ((latest.power_zones or {}).get("critical_power_w")) if latest else None
    try:
        return int(round(float(cp))) if cp else None
    except (TypeError, ValueError):
        return None


def get_cp_status(session, user_id, today: date) -> dict:
    from backend.models import UserPreferences

    prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    out = evaluate_cp_staleness(
        load_recent_runs(session, user_id, today),
        getattr(prefs, "ftp_w", None),
        getattr(prefs, "ftp_w_updated_at", None),
        today,
        latest_stryd_cp(session, user_id),
    )
    out["cp_source"] = getattr(prefs, "ftp_w_source", None)
    return out


def validate_cp(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, int) or not (CP_MIN_W <= value <= CP_MAX_W):
        return f"cp_w must be an integer between {CP_MIN_W} and {CP_MAX_W}"
    return None


def record_cp_history(session, user_id, cp_w: int, previous: Optional[int], source: str, effective: date) -> None:
    from backend.models import CpHistory

    session.add(
        CpHistory(
            user_id=user_id,
            cp_w=cp_w,
            previous_cp_w=previous,
            source=source,
            effective_date=effective,
        )
    )


def apply_cp_update(session, user_id, cp_w: int, source: str, today: date) -> dict:
    """Write confirmed CP to preferences + history. Caller commits."""
    from backend.models import UserPreferences

    prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        session.add(prefs)
    previous = prefs.ftp_w
    prefs.ftp_w = cp_w
    prefs.ftp_w_source = source
    prefs.ftp_w_updated_at = datetime.now(timezone.utc)
    record_cp_history(session, user_id, cp_w, previous, source, today)
    return {"cp_w": cp_w, "previous_cp_w": previous, "source": source, "effective_date": today.isoformat()}


def list_cp_history(session, user_id) -> list[dict]:
    from sqlalchemy import desc

    from backend.models import CpHistory

    rows = (
        session.query(CpHistory)
        .filter(CpHistory.user_id == user_id)
        .order_by(desc(CpHistory.effective_date), desc(CpHistory.created_at))
        .all()
    )
    return [
        {
            "id": str(r.id),
            "cp_w": r.cp_w,
            "previous_cp_w": r.previous_cp_w,
            "source": r.source,
            "effective_date": r.effective_date.isoformat(),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
