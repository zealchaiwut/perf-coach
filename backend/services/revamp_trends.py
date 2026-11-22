"""Training Trends top half (P5-3): fitness chart + weekly load for a date range."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.services.revamp_load_plan import week_target_and_phase
from backend.services.training_load import get_snapshot_series
from backend.services.weekly_rollup import bangkok_week_start, normalize_week_start, weekly_rollups
from backend.utils.time import today_bangkok

RANGE_KEYS = frozenset({"4w", "3m", "6m", "12m"})
RANGE_DEFAULT = "3m"

# Inclusive day counts ending on ``today``.
_RANGE_DAYS: dict[str, int] = {
    "4w": 28,
    "3m": 91,
    "6m": 183,
    "12m": 365,
}

_PHASE_SHADE = frozenset({"taper", "race_week"})


def normalize_range_key(key: Optional[str]) -> str:
    k = (key or RANGE_DEFAULT).strip().lower()
    return k if k in RANGE_KEYS else RANGE_DEFAULT


def range_dates(range_key: str, today: date) -> tuple[date, date]:
    """Inclusive ``from``/``to`` calendar dates for the range ending on ``today``."""
    days = _RANGE_DAYS[normalize_range_key(range_key)]
    to_d = today
    from_d = today - timedelta(days=days - 1)
    return from_d, to_d


def is_planned_down_week(target: Optional[float], prev_target: Optional[float]) -> bool:
    if target is None or prev_target is None or prev_target <= 0:
        return False
    return float(target) < 0.85 * float(prev_target)


def _merge_phase_spans(week_phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive weeks with the same shaded phase."""
    spans: list[dict[str, Any]] = []
    for row in week_phases:
        phase = row.get("phase")
        if phase not in _PHASE_SHADE:
            continue
        start = row["week_start"]
        end = row["week_end"]
        start_d = date.fromisoformat(start) if isinstance(start, str) else start
        end_s = end if isinstance(end, str) else end.isoformat()
        start_s = start if isinstance(start, str) else start.isoformat()
        if (
            spans
            and spans[-1]["phase"] == phase
            and spans[-1]["end"] == (start_d - timedelta(days=1)).isoformat()
        ):
            spans[-1]["end"] = end_s
        else:
            spans.append(
                {
                    "phase": phase,
                    "start": start_s,
                    "end": end_s,
                    "label": "Taper" if phase == "taper" else "Race week",
                }
            )
    return spans


def build_phase_spans(
    session: Session,
    user_id: uuid.UUID,
    from_d: date,
    to_d: date,
    *,
    today: date,
) -> list[dict[str, Any]]:
    ws = bangkok_week_start(from_d)
    we = bangkok_week_start(to_d)
    week_rows: list[dict[str, Any]] = []
    cursor = ws
    while cursor <= we:
        we_day = cursor + timedelta(days=6)
        meta = week_target_and_phase(user_id, cursor, session=session, today=today) or {}
        phase = meta.get("phase")
        if phase in _PHASE_SHADE:
            week_rows.append(
                {
                    "week_start": cursor.isoformat(),
                    "week_end": we_day.isoformat(),
                    "phase": phase,
                }
            )
        cursor += timedelta(days=7)
    return _merge_phase_spans(week_rows)


def build_fitness_series(user_id: uuid.UUID, from_d: date, to_d: date, *, today: date) -> list[dict[str, Any]]:
    cap = min(to_d, today)
    if from_d > cap:
        return []
    rows = get_snapshot_series(str(user_id), from_d, cap)
    return [
        {
            "date": r["date"].isoformat(),
            "tss": r.get("tss"),
            "ctl": round(float(r["ctl"]), 1),
            "atl": round(float(r["atl"]), 1),
            "tsb": round(float(r["tsb"]), 1),
        }
        for r in rows
    ]


def build_weekly_load(
    session: Session,
    user_id: uuid.UUID,
    from_d: date,
    to_d: date,
    *,
    today: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fw = bangkok_week_start(from_d)
    tw = bangkok_week_start(to_d)
    current_ws = normalize_week_start(today)
    rollups = weekly_rollups(user_id, fw, tw, session=session, today=today)
    prev_target: Optional[float] = None
    weeks: list[dict[str, Any]] = []
    sum_tss = 0.0
    sum_km = 0.0
    sum_h = 0.0
    n = 0
    for row in rollups:
        target = row.get("target_tss")
        down = is_planned_down_week(target, prev_target)
        if target is not None:
            prev_target = float(target)
        ws = row["week_start"]
        is_current = ws == current_ws.isoformat()
        logged = float(row.get("tss_total") or 0)
        planned = float(row.get("planned_tss") or 0)
        outline = None
        if is_current:
            outline = round(target if target is not None else logged + planned, 1)
        weeks.append(
            {
                "week_start": ws,
                "tss_total": logged,
                "distance_km": row.get("distance_km"),
                "hours": row.get("hours"),
                "target_tss": target,
                "phase": row.get("phase"),
                "planned_down_week": down,
                "is_current_week": is_current,
                "outline_tss": outline,
                "partial": bool(row.get("partial")),
            }
        )
        sum_tss += logged
        sum_km += float(row.get("distance_km") or 0)
        sum_h += float(row.get("hours") or 0)
        n += 1
    avg = {
        "tss_total": round(sum_tss / n, 1) if n else 0,
        "distance_km": round(sum_km / n, 1) if n else 0,
        "hours": round(sum_h / n, 1) if n else 0,
        "week_count": n,
    }
    return weeks, avg


def fitness_subtitle(series: list[dict[str, Any]]) -> str:
    if len(series) < 2:
        return "Chronic and acute load over your selected range."
    first_ctl = series[0].get("ctl")
    last_ctl = series[-1].get("ctl")
    if first_ctl is None or last_ctl is None:
        return "Chronic and acute load over your selected range."
    delta = round(last_ctl - first_ctl, 1)
    if abs(delta) < 2:
        trend = "holding steady"
    elif delta > 0:
        trend = f"chronic load up about {delta:g} points"
    else:
        trend = f"chronic load down about {abs(delta):g} points"
    return f"Fitness and fatigue across the range · {trend}"


def trends_payload(
    session: Session,
    user_id: uuid.UUID,
    *,
    range_key: Optional[str] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    rk = normalize_range_key(range_key)
    from_d, to_d = range_dates(rk, today)
    curves = build_fitness_series(user_id, from_d, to_d, today=today)
    current = curves[-1] if curves else None
    phase_spans = build_phase_spans(session, user_id, from_d, to_d, today=today)
    weeks, block_avg = build_weekly_load(session, user_id, from_d, to_d, today=today)
    return {
        "range": rk,
        "from": from_d.isoformat(),
        "to": to_d.isoformat(),
        "as_of": today.isoformat(),
        "fitness": {
            "subtitle": fitness_subtitle(curves),
            "curves": curves,
            "current": current,
            "phase_spans": phase_spans,
        },
        "weekly_load": {
            "weeks": weeks,
            "block_average": block_avg,
        },
    }