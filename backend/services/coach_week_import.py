"""Parse and commit coach-week paste imports (revamp P3-6)."""
from __future__ import annotations

import re
import statistics
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession, Workout
from backend.services.weekly_rollup import normalize_week_start
from backend.utils.time import today_bangkok

_DAY_MAP = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

_TYPE_IF = {
    "easy": 0.70,
    "long": 0.75,
    "tempo": 0.87,
    "interval": 0.90,
    "intervals": 0.90,
    "hills": 0.90,
    "race": 0.92,
    "rest": 0.0,
}

_LINE_RE = re.compile(
    r"^\s*"
    r"(?P<day>[a-z]+)\s+"
    r"(?P<type>easy|long|tempo|interval|intervals|hills|race|rest)\b"
    r"(?:\s+(?P<rest>.+))?"
    r"\s*$",
    re.IGNORECASE,
)
_MIN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:min(?:ute)?s?|m)\b", re.IGNORECASE)
_HR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*h(?:ours?)?\b", re.IGNORECASE)
_KM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*km\b", re.IGNORECASE)
_REP_KM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*km\s*[x×]\s*(\d+)\b",
    re.IGNORECASE,
)


def _tss_from_duration(duration_min: float, run_type: str) -> float:
    if run_type == "rest" or duration_min <= 0:
        return 0.0
    intensity = _TYPE_IF.get(run_type, 0.75)
    hours = duration_min / 60.0
    return round(hours * (intensity**2) * 100.0, 1)


def median_easy_pace_sec_per_km(session: Session, user_id: uuid.UUID, today: date) -> Optional[float]:
    """Median sec/km on easy runs in the trailing 28 days."""
    cutoff = today - timedelta(days=27)
    rows = (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= cutoff,
            Workout.workout_date <= today,
            Workout.workout_type == "run",
            Workout.run_subtype == "easy",
            Workout.distance_km.isnot(None),
            Workout.distance_km > 0,
            Workout.duration_seconds.isnot(None),
            Workout.duration_seconds > 0,
        )
        .all()
    )
    paces = [float(w.duration_seconds) / float(w.distance_km) for w in rows]
    if not paces:
        return None
    return float(statistics.median(paces))


def _duration_from_distance(
    distance_km: float,
    *,
    pace_sec_per_km: Optional[float],
) -> tuple[Optional[float], bool]:
    if pace_sec_per_km is None or distance_km <= 0:
        return None, False
    return round((distance_km * pace_sec_per_km) / 60.0, 1), True


def _title_name(run_type: str, detail: str) -> str:
    base = run_type.capitalize()
    d = (detail or "").strip()
    return f"{base} {d}".strip() if d else base


def parse_coach_week_line(
    line: str,
    *,
    week_start: date,
    line_index: int,
    median_pace: Optional[float] = None,
) -> dict[str, Any]:
    raw = (line or "").strip()
    if not raw:
        return {
            "line_index": line_index,
            "raw": raw,
            "parse_status": "empty",
            "blocks_commit": True,
        }
    m = _LINE_RE.match(raw)
    if not m:
        return {
            "line_index": line_index,
            "raw": raw,
            "parse_status": "unparsed",
            "blocks_commit": True,
        }
    day_tok = m.group("day").lower()
    weekday = _DAY_MAP.get(day_tok)
    if weekday is None:
        return {
            "line_index": line_index,
            "raw": raw,
            "parse_status": "unparsed",
            "blocks_commit": True,
        }
    run_type = m.group("type").lower()
    if run_type == "intervals":
        run_type = "interval"
    rest = (m.group("rest") or "").strip()
    ws = normalize_week_start(week_start)
    planned_date = ws + timedelta(days=weekday)

    duration_min: Optional[float] = None
    distance_km: Optional[float] = None
    inferred = False

    if run_type == "rest":
        duration_min = 0.0
    else:
        rep = _REP_KM_RE.search(rest)
        if rep:
            distance_km = float(rep.group(1)) * int(rep.group(2))
        else:
            km = _KM_RE.search(rest)
            if km:
                distance_km = float(km.group(1))
        mins = _MIN_RE.search(rest)
        hrs = _HR_RE.search(rest)
        if mins:
            duration_min = float(mins.group(1))
        elif hrs:
            duration_min = float(hrs.group(1)) * 60.0
        elif distance_km is not None:
            duration_min, inferred = _duration_from_distance(distance_km, pace_sec_per_km=median_pace)

    if run_type != "rest" and (duration_min is None or duration_min <= 0):
        return {
            "line_index": line_index,
            "raw": raw,
            "parse_status": "unparsed",
            "blocks_commit": True,
        }

    tss = _tss_from_duration(duration_min or 0.0, run_type)
    session_type = "rest" if run_type == "rest" else "run"
    structure = None
    if session_type == "run":
        structure = {
            "duration_minutes": duration_min,
            "target_tss": tss,
            "run_subtype": run_type,
            "distance_km": distance_km,
        }
        if inferred:
            structure["inferred_duration"] = True

    return {
        "line_index": line_index,
        "raw": raw,
        "parse_status": "ok",
        "blocks_commit": False,
        "weekday": weekday,
        "planned_date": planned_date.isoformat(),
        "session_type": session_type,
        "run_type": run_type,
        "name": _title_name(run_type, rest),
        "duration_minutes": duration_min,
        "distance_km": distance_km,
        "target_tss": tss,
        "inferred": inferred,
        "structure": structure,
    }


def parse_coach_week_text(
    session: Session,
    user_id: uuid.UUID,
    *,
    week_start: date,
    text: str,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    median_pace = median_easy_pace_sec_per_km(session, user_id, today)
    lines = (text or "").splitlines()
    rows = [
        parse_coach_week_line(
            line,
            week_start=week_start,
            line_index=i,
            median_pace=median_pace,
        )
        for i, line in enumerate(lines)
        if line.strip()
    ]
    return {
        "week_start": normalize_week_start(week_start).isoformat(),
        "median_easy_pace_sec_per_km": median_pace,
        "rows": rows,
        "commit_allowed": not any(r.get("blocks_commit") for r in rows),
    }


def validate_commit_rows(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        if r.get("parse_status") == "unparsed" or r.get("blocks_commit"):
            raise ValueError(f"unparsed line blocks commit: {r.get('raw', '')[:80]}")


def _coach_replaceable(row: PlannedSession, today: date) -> bool:
    if (row.plan_source or "").lower() != "coach":
        return False
    if row.matched_workout_id is not None:
        return False
    if (row.status or "").lower() in ("done_auto", "done_manual"):
        return False
    if row.planned_date < today:
        return False
    return True


def apply_coach_week_import(
    session: Session,
    user_id: uuid.UUID,
    *,
    week_start: date,
    rows: list[dict[str, Any]],
    today: Optional[date] = None,
    reimport: bool = True,
) -> dict[str, Any]:
    """Commit parsed rows; on re-import drop only future unmatched coach rows."""
    today = today or today_bangkok()
    validate_commit_rows(rows)
    ws = normalize_week_start(week_start)
    we = ws + timedelta(days=6)
    removed = 0
    if reimport:
        existing = (
            session.query(PlannedSession)
            .filter(
                PlannedSession.user_id == user_id,
                PlannedSession.planned_date >= ws,
                PlannedSession.planned_date <= we,
                PlannedSession.plan_source == "coach",
            )
            .all()
        )
        for row in existing:
            if _coach_replaceable(row, today):
                session.delete(row)
                removed += 1

    created = 0
    for r in rows:
        if r.get("session_type") == "rest":
            st = "rest"
        else:
            st = "run"
        planned_date = date.fromisoformat(str(r["planned_date"])[:10])
        row = PlannedSession(
            user_id=user_id,
            planned_date=planned_date,
            session_type=st,
            name=r.get("name"),
            structure=r.get("structure"),
            plan_source="coach",
            status="planned",
        )
        session.add(row)
        created += 1
    return {
        "week_start": ws.isoformat(),
        "created": created,
        "removed": removed,
    }


def row_from_commit_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize editable confirm-table row back into a committable row."""
    run_type = (raw.get("run_type") or "easy").lower()
    duration = raw.get("duration_minutes")
    try:
        duration_f = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_f = None
    tss = raw.get("target_tss")
    if tss is None and duration_f is not None:
        tss = _tss_from_duration(duration_f, run_type)
    structure = raw.get("structure")
    if raw.get("session_type") == "run" or run_type != "rest":
        structure = {
            "duration_minutes": duration_f,
            "target_tss": tss,
            "run_subtype": run_type,
            "distance_km": raw.get("distance_km"),
        }
        if raw.get("inferred"):
            structure["inferred_duration"] = True
    return {
        "parse_status": "ok",
        "blocks_commit": False,
        "planned_date": raw["planned_date"],
        "session_type": "rest" if run_type == "rest" else "run",
        "run_type": run_type,
        "name": raw.get("name"),
        "duration_minutes": duration_f,
        "distance_km": raw.get("distance_km"),
        "target_tss": tss,
        "inferred": bool(raw.get("inferred")),
        "structure": structure,
    }