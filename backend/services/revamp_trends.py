"""Training Trends (P5-3 / P5-4): fitness, load, decoupling, form, zone mix."""
from __future__ import annotations

import statistics
import uuid
from calendar import month_name
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.services import axis_durability, axis_economy, axis_strength
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


DECOUPLING_REF_PCT = 5.0
MEDIAN_LAST_N = 4
FORM_METRICS = (
    ("easy_power_w", "power_w", "Easy-run power", " W"),
    ("power_to_weight", "power_to_weight", "Power to weight", " W/kg"),
    ("cadence_spm", "cadence_spm", "Cadence", " spm"),
    ("lss_kn_m", "lss_kn_m", "Leg spring stiffness", " kN/m"),
    ("gct_ms", "gct_ms", "Ground contact", " ms"),
    ("form_power_ratio", "form_power_ratio", "Form power ratio", "%"),
)
def _median_key(rows: list[Any], key: str) -> Optional[float]:
    vals = [float(axis_economy._get(r, key)) for r in rows if axis_economy._get(r, key) is not None]
    return float(statistics.median(vals)) if vals else None


def fetch_easy_form_rows(session: Session, user_id: uuid.UUID, from_d: date, to_d: date) -> list[dict[str, Any]]:
    """Easy runs with form metrics in ``[from_d, to_d]`` (same easy rule as P4-3)."""
    from backend.models import RunFormMetrics as F, Workout as W

    q = (
        session.query(W, F)
        .join(F, F.workout_id == W.id)
        .filter(
            W.user_id == user_id,
            W.workout_type.ilike("run"),
            W.workout_date >= from_d,
            W.workout_date <= to_d,
        )
    )
    out: list[dict[str, Any]] = []
    for w, f in q.all():
        row = {
            "workout_id": str(w.id),
            "workout_date": w.workout_date,
            "name": w.name,
            "duration_seconds": w.duration_seconds,
            "zone2_minutes": w.zone2_minutes,
            "lss_kn_m": axis_economy._num(f.lss_kn_m),
            "gct_ms": axis_economy._num(f.gct_ms),
            "form_power_ratio": axis_economy._num(f.form_power_ratio),
            "power_w": axis_economy._num(f.power_w),
            "cadence_spm": axis_economy._num(f.cadence_spm),
        }
        if not axis_economy.is_easy_run(row):
            continue
        if all(row.get(k) is None for k in ("lss_kn_m", "gct_ms", "form_power_ratio", "power_w", "cadence_spm")):
            continue
        out.append(row)
    return out


def build_decoupling_panel(
    session: Session,
    user_id: uuid.UUID,
    from_d: date,
    to_d: date,
    *,
    today: date,
) -> dict[str, Any]:
    runs = axis_durability.fetch_runs(session, user_id, today)
    qualifying = [r for r in runs if axis_durability.is_qualifying_run(r)]
    in_range = [
        r
        for r in qualifying
        if from_d <= r.workout_date <= to_d
    ]
    in_range.sort(key=lambda r: r.workout_date)
    points = [
        {
            "date": r.workout_date.isoformat(),
            "decoupling_percent": round(float(r.decoupling_percent), 1),
            "name": r.name,
        }
        for r in in_range
    ]
    used = qualifying[:MEDIAN_LAST_N]
    median = (
        float(statistics.median(float(r.decoupling_percent) for r in used)) if len(used) >= 2 else None
    )
    note = None
    if median is not None and points:
        worst = max(points, key=lambda p: p["decoupling_percent"])
        if worst["decoupling_percent"] >= 2.0 * median:
            try:
                d = date.fromisoformat(worst["date"])
                label = f"{month_name[d.month]} outlier"
            except ValueError:
                label = "One outlier"
            note = (
                f"The {label} ({worst['decoupling_percent']}%) was well above the "
                f"recent median ({median:.1f}%)."
            )
    return {
        "points": points,
        "reference_pct": DECOUPLING_REF_PCT,
        "median_last_4_pct": round(median, 1) if median is not None else None,
        "note": note,
        "qualifier": "axis_durability.is_qualifying_run",
    }


def _fmt_delta(curr: Optional[float], prev: Optional[float], *, decimals: int = 1, suffix: str = "") -> Optional[str]:
    if curr is None or prev is None:
        return None
    d = round(curr - prev, decimals)
    if abs(d) < 10 ** (-decimals):
        return "flat"
    sign = "+" if d > 0 else "\u2212"
    return f"{sign}{abs(d):g}{suffix}"


def build_form_tiles(
    session: Session,
    user_id: uuid.UUID,
    from_d: date,
    to_d: date,
    *,
    today: date,
) -> dict[str, Any]:
    rows = fetch_easy_form_rows(session, user_id, from_d, to_d)
    pool_now = axis_economy.easy_pool(rows, today)
    past = today - timedelta(days=28)
    past_rows = fetch_easy_form_rows(session, user_id, past - timedelta(days=27), past)
    pool_past = axis_economy.easy_pool(past_rows, past)
    mass_now, _ = axis_strength.fetch_trend_mass(session, user_id, today)
    mass_past, _ = axis_strength.fetch_trend_mass(session, user_id, past)

    def ptw(pool: list[Any], mass: Optional[float]) -> Optional[float]:
        pw = axis_economy.median_power_w(pool)
        if pw is None or not mass:
            return None
        return round(pw / float(mass), 2)

    focus_economy = False
    try:
        from backend.services import focus_ranking
        from backend.services.radar_payload import build_radar

        ranked = focus_ranking.rank_axes(build_radar(session, user_id, today)["axes"], None)
        focus = ranked.get("focus") or {}
        if focus.get("axis") == "economy":
            focus_economy = True
    except Exception:
        pass

    tiles: list[dict[str, Any]] = []
    for tile_id, key, label, suffix in FORM_METRICS:
        if key == "power_to_weight":
            cur = ptw(pool_now, mass_now)
            prev = ptw(pool_past, mass_past)
            spark_vals = []
            by_week: dict[str, list] = {}
            for r in rows:
                if mass_now is None or axis_economy._get(r, "power_w") is None:
                    continue
                ws = bangkok_week_start(axis_economy._get(r, "workout_date")).isoformat()
                by_week.setdefault(ws, []).append(float(axis_economy._get(r, "power_w")) / mass_now)
            for ws in sorted(by_week):
                spark_vals.append({"x": ws, "value": round(statistics.median(by_week[ws]), 2)})
        elif key == "form_power_ratio":
            cur = _median_key(pool_now, key)
            if cur is not None:
                cur = round(cur * 100.0, 0)
            prev_med = _median_key(pool_past, key)
            prev = round(prev_med * 100.0, 0) if prev_med is not None else None
            spark_vals = _weekly_spark(rows, key, scale=100.0)
        else:
            cur = _median_key(pool_now, key)
            if cur is not None and key in ("power_w",):
                cur = round(cur, 0)
            elif cur is not None:
                cur = round(cur, 1)
            prev_raw = _median_key(pool_past, key)
            prev = round(prev_raw, 0) if key == "power_w" and prev_raw is not None else (
                round(prev_raw, 1) if prev_raw is not None else None
            )
            spark_vals = _weekly_spark(rows, key)

        tiles.append(
            {
                "id": tile_id,
                "label": label,
                "value": cur,
                "value_suffix": suffix.strip(),
                "delta_28d": _fmt_delta(cur, prev, suffix=suffix.strip()),
                "sparkline": spark_vals,
                "economy_focus": focus_economy and tile_id in ("lss_kn_m", "gct_ms"),
                "pool": "axis_economy.easy_pool",
            }
        )
    return {"tiles": tiles}


def _weekly_spark(rows: list[Any], key: str, *, scale: float = 1.0) -> list[dict[str, Any]]:
    by_week: dict[str, list[float]] = {}
    for r in rows:
        val = axis_economy._get(r, key)
        if val is None:
            continue
        ws = bangkok_week_start(axis_economy._get(r, "workout_date")).isoformat()
        by_week.setdefault(ws, []).append(float(val) * scale)
    return [{"x": ws, "value": round(statistics.median(vals), 2)} for ws, vals in sorted(by_week.items())]


def build_zone_mix(
    session: Session,
    user_id: uuid.UUID,
    from_d: date,
    to_d: date,
    *,
    today: date,
) -> dict[str, Any]:
    from backend.models import StrydActivity, Workout

    rows = (
        session.query(Workout.workout_date, StrydActivity.power_zones)
        .join(StrydActivity, Workout.stryd_activity_pk == StrydActivity.id)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= from_d,
            Workout.workout_date <= to_d,
        )
        .all()
    )
    buckets: dict[str, list[float]] = {}
    for wd, pz in rows:
        if not pz or not isinstance(pz, dict):
            continue
        secs = pz.get("seconds_in_zones")
        if not isinstance(secs, list) or len(secs) < 5:
            continue
        ym = f"{wd.year:04d}-{wd.month:02d}"
        if ym not in buckets:
            buckets[ym] = [0.0] * 5
        for i in range(5):
            buckets[ym][i] += float(secs[i] or 0)

    months: list[dict[str, Any]] = []
    cursor = date(from_d.year, from_d.month, 1)
    end_month = date(to_d.year, to_d.month, 1)
    while cursor <= end_month:
        ym = f"{cursor.year:04d}-{cursor.month:02d}"
        secs = buckets.get(ym, [0.0] * 5)
        total_sec = sum(secs)
        if total_sec > 0:
            shares = [round(s / total_sec * 100.0, 1) for s in secs]
            months.append(
                {
                    "month": ym,
                    "label": month_name[cursor.month],
                    "zone_hours": [round(s / 3600.0, 1) for s in secs],
                    "zone_pct": shares,
                    "total_hours": round(total_sec / 3600.0, 1),
                    "partial": cursor.year == today.year and cursor.month == today.month,
                }
            )
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return {"months": months}


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
        "decoupling": build_decoupling_panel(session, user_id, from_d, to_d, today=today),
        "form_tiles": build_form_tiles(session, user_id, from_d, to_d, today=today),
        "zone_mix": build_zone_mix(session, user_id, from_d, to_d, today=today),
    }