"""Strength and power-to-weight axis scores (revamp P4-4).

Strength
    Anchor lifts are a per-user settings list (``user_preferences.anchor_lifts``,
    default single-leg deadlift 0.6 and calf raise 1.2 x trend mass). Per session
    and lift, e1RM = kg x (1 + reps / 30) from the best set; ``8/side`` counts as
    8 reps. Ratio per anchor = best e1RM of the last 45 days / (target factor x
    trend mass). Score = clamp(mean ratio x 100, 0, 100).

    An anchor with no session in the 45-day window falls back to the best e1RM in
    the 45 days before its latest session, and the axis is flagged *stale* —
    old, never wrong, and distinct from never-measured.

Power-to-weight
    raw = median power of the P4-3 easy pool (``axis_economy.easy_pool``) /
    trend mass. Score = clamp(raw / profile target x 100, 0, 100); profile target
    comes from the A-race goal (P4-1 table; the 3:30 row, 3.2 W/kg, when no goal).
    Missing weigh-ins make the axis *stale* (> 14 days) — the score still uses the
    last trend mass, so it is old, not wrong. No weigh-in at all = never-measured.

Trend mass comes from ``weight_ewma.compute_ewma`` (the weight tab is retired;
only this reader is used).
"""
from __future__ import annotations

import json
import re
import statistics
import uuid
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional

from backend.services import axis_economy
from backend.services.axis_spec import (
    interpolate_marathon_profile,
    profile_for_race_goal,
    staleness_power_to_weight,
    staleness_strength,
)
from backend.services.weight_ewma import DEFAULT_SPAN, compute_ewma

WINDOW_DAYS = 45
DEFAULT_PROFILE_MARATHON_SECONDS = 12600  # 3:30 row, 3.2 W/kg
WEIGHT_LOOKBACK_DAYS = 120

DEFAULT_ANCHOR_LIFTS: tuple[dict[str, Any], ...] = (
    {
        "key": "single_leg_deadlift",
        "label": "Single-leg deadlift",
        "target_factor": 0.6,
        "match": ["single leg deadlift", "single-leg deadlift", "single leg rdl", "single-leg rdl", "sldl"],
    },
    {
        "key": "calf_raise",
        "label": "Calf raise",
        "target_factor": 1.2,
        "match": ["calf raise"],
    },
)


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------

_REPS_RE = re.compile(r"\d+(?:\.\d+)?")


def parse_reps(reps: Any) -> Optional[float]:
    """Reps as a number; ``8/side`` and ``10 per side`` count as 8 and 10."""
    if reps is None or isinstance(reps, bool):
        return None
    if isinstance(reps, (int, float)):
        return float(reps) if reps > 0 else None
    m = _REPS_RE.search(str(reps))
    if not m:
        return None
    v = float(m.group(0))
    return v if v > 0 else None


def e1rm(weight_kg: Any, reps: Any) -> Optional[float]:
    """Epley estimate: kg x (1 + reps / 30). None for unloaded or rep-less sets."""
    try:
        w = float(weight_kg)
    except (TypeError, ValueError):
        return None
    r = parse_reps(reps)
    if r is None or w <= 0:
        return None
    return w * (1.0 + r / 30.0)


def best_set_e1rm(sets: Iterable[Mapping[str, Any]]) -> Optional[float]:
    best = None
    for s in sets:
        if (s.get("type") or "working") == "warmup":
            continue
        v = e1rm(s.get("weight", s.get("weight_kg")), s.get("reps"))
        if v is not None and (best is None or v > best):
            best = v
    return best


def exercise_sets(ex: Any) -> list[dict[str, Any]]:
    """Per-set dicts for a logged exercise (sets_json first, summary columns as fallback)."""
    raw = ex.get("sets_json") if isinstance(ex, Mapping) else getattr(ex, "sets_json", None)
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list) and parsed:
                return [s for s in parsed if isinstance(s, Mapping)]
        except (TypeError, ValueError):
            pass
    get = ex.get if isinstance(ex, Mapping) else (lambda k: getattr(ex, k, None))
    return [{"weight": get("weight_kg"), "reps": get("reps"), "type": "working"}]


def matches_anchor(name: str, anchor: Mapping[str, Any]) -> bool:
    low = (name or "").lower()
    return any(m.lower() in low for m in anchor.get("match", []) if m)


def normalize_anchor_lifts(raw: Any) -> list[dict[str, Any]]:
    """Validate a stored list; fall back to the defaults when empty/invalid."""
    out = []
    if isinstance(raw, list):
        for a in raw:
            if not isinstance(a, Mapping):
                continue
            try:
                factor = float(a.get("target_factor"))
            except (TypeError, ValueError):
                continue
            label = str(a.get("label") or a.get("key") or "").strip()
            match = [str(m).strip() for m in (a.get("match") or []) if str(m).strip()] or (
                [label.lower()] if label else []
            )
            if factor <= 0 or not label or not match:
                continue
            out.append({
                "key": str(a.get("key") or re.sub(r"\W+", "_", label.lower()).strip("_")),
                "label": label,
                "target_factor": factor,
                "match": match,
            })
    return out or [dict(a) for a in DEFAULT_ANCHOR_LIFTS]


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def strength_ratio(best_e1rm: float, target_factor: float, trend_mass_kg: float) -> float:
    return best_e1rm / (target_factor * trend_mass_kg)


def strength_score(ratios: list[float]) -> Optional[int]:
    if not ratios:
        return None
    return int(round(_clamp(statistics.mean(ratios) * 100.0)))


def power_to_weight_raw(median_power_w: float, trend_mass_kg: float) -> float:
    return median_power_w / trend_mass_kg


def power_to_weight_score(raw_w_per_kg: float, target_w_per_kg: float) -> int:
    return int(round(_clamp(raw_w_per_kg / target_w_per_kg * 100.0)))


def trend_mass_from_entries(entries: list[Mapping[str, Any]]) -> Optional[float]:
    """Latest EWMA value from chronological ``{date, weight_kg}`` entries."""
    if not entries:
        return None
    return float(compute_ewma(entries, span=DEFAULT_SPAN)[-1])


# ---------------------------------------------------------------------------
# Strength axis from logged lifts
# ---------------------------------------------------------------------------


def compute_strength(
    sessions: Iterable[Mapping[str, Any]],
    anchors: list[dict[str, Any]],
    trend_mass_kg: Optional[float],
    as_of: date,
) -> dict[str, Any]:
    """``sessions``: ``{workout_date, name, sets_json?, weight_kg?, reps?}`` per logged exercise."""
    window_start = as_of - timedelta(days=WINDOW_DAYS)
    # per anchor key -> list of (date, e1rm) per exercise row
    per_anchor: dict[str, list[tuple[date, float]]] = {a["key"]: [] for a in anchors}
    for s in sessions:
        d = s["workout_date"]
        if d > as_of:
            continue
        for a in anchors:
            if matches_anchor(s.get("name", ""), a):
                v = best_set_e1rm(exercise_sets(s))
                if v is not None:
                    per_anchor[a["key"]].append((d, v))

    logged_in_window = any(
        d >= window_start for rows in per_anchor.values() for d, _ in rows
    )
    stale = staleness_strength(logged_in_window)
    ratios: list[float] = []
    detail = []
    latest_date: Optional[date] = None
    for a in anchors:
        rows = per_anchor[a["key"]]
        item: dict[str, Any] = {
            "key": a["key"], "label": a["label"], "target_factor": a["target_factor"],
            "best_e1rm_kg": None, "ratio": None, "last_logged": None,
        }
        if rows:
            last = max(d for d, _ in rows)
            ref_end = as_of if last >= window_start else last
            lo = ref_end - timedelta(days=WINDOW_DAYS)
            best = max(v for d, v in rows if lo <= d <= ref_end)
            item["best_e1rm_kg"] = round(best, 2)
            item["last_logged"] = last.isoformat()
            latest_date = last if latest_date is None else max(latest_date, last)
            if trend_mass_kg:
                ratio = strength_ratio(best, a["target_factor"], trend_mass_kg)
                item["ratio"] = round(ratio, 3)
                ratios.append(ratio)
        detail.append(item)

    score = strength_score(ratios) if trend_mass_kg else None
    return {
        "axis": "strength",
        "score": score,
        "raw": round(statistics.mean(ratios), 3) if ratios and trend_mass_kg else None,
        "unit": "mean_ratio",
        "anchors": detail,
        "trend_mass_kg": round(trend_mass_kg, 2) if trend_mass_kg else None,
        "never_measured": score is None,
        "stale": stale,
        "delta_28d": None,
        "anchor_date": latest_date.isoformat() if latest_date else None,
        "anchor_title": None,
    }


def compute_power_to_weight(
    pool: list[Any],
    trend_mass_kg: Optional[float],
    days_since_weigh_in: Optional[int],
    target_w_per_kg: float,
) -> dict[str, Any]:
    """``pool`` is the P4-3 easy pool (rows carrying ``power_w``)."""
    median_w = axis_economy.median_power_w(pool)
    block: dict[str, Any] = {
        "axis": "power_to_weight",
        "score": None,
        "raw": None,
        "unit": "w_per_kg",
        "target_w_per_kg": round(target_w_per_kg, 3),
        "median_power_w": median_w,
        "trend_mass_kg": round(trend_mass_kg, 2) if trend_mass_kg else None,
        "never_measured": True,
        "stale": staleness_power_to_weight(days_since_weigh_in),
        "days_since_weigh_in": days_since_weigh_in,
        "delta_28d": None,
        "anchor_date": None,
        "anchor_title": None,
    }
    if median_w is None or not trend_mass_kg or target_w_per_kg <= 0:
        return block
    raw = power_to_weight_raw(median_w, trend_mass_kg)
    block.update(
        score=power_to_weight_score(raw, target_w_per_kg),
        raw=round(raw, 3),
        never_measured=False,
    )
    return block


# ---------------------------------------------------------------------------
# DB readers
# ---------------------------------------------------------------------------


def fetch_trend_mass(session, user_id: uuid.UUID, as_of: date) -> tuple[Optional[float], Optional[int]]:
    """(trend mass kg, days since last weigh-in) from ``weight_entries``."""
    from backend.models import WeightEntry as W

    rows = (
        session.query(W.entry_date, W.weight_kg)
        .filter(
            W.user_id == user_id,
            W.entry_date <= as_of,
            W.entry_date >= as_of - timedelta(days=WEIGHT_LOOKBACK_DAYS),
        )
        .order_by(W.entry_date.asc())
        .all()
    )
    if not rows:
        return None, None
    entries = [{"date": r.entry_date, "weight_kg": float(r.weight_kg)} for r in rows]
    return trend_mass_from_entries(entries), (as_of - rows[-1].entry_date).days


def get_anchor_lifts(session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    from backend.models import UserPreferences as P

    row = session.query(P).filter(P.user_id == user_id).first()
    return normalize_anchor_lifts(getattr(row, "anchor_lifts", None) if row else None)


def fetch_lift_rows(session, user_id: uuid.UUID, as_of: date, anchors: list[dict[str, Any]]) -> list[dict]:
    """Logged exercises whose name matches any anchor (all history; the rules window it)."""
    from sqlalchemy import or_
    from backend.models import Workout as W, WorkoutExercise as E

    conds = [E.name.ilike(f"%{m}%") for a in anchors for m in a["match"]]
    if not conds:
        return []
    q = (
        session.query(W.workout_date, E)
        .join(E, E.workout_id == W.id)
        .filter(W.user_id == user_id, W.workout_date <= as_of, or_(*conds))
        .order_by(W.workout_date.desc())
        .limit(400)
    )
    return [
        {
            "workout_date": d, "name": e.name, "sets_json": e.sets_json,
            "weight_kg": float(e.weight_kg) if e.weight_kg is not None else None, "reps": e.reps,
            "workout_id": str(getattr(e, "workout_id", "") or ""),
            "sets": getattr(e, "sets", None),
        }
        for d, e in q.all()
    ]


def profile_target_w_per_kg(session, user_id: uuid.UUID, as_of: date) -> float:
    """Power-to-weight target from the next A-race goal (P4-1), else the 3:30 row."""
    from backend.services.perf_a_race import next_a_race

    race = next_a_race(session, user_id, as_of)
    prof = None
    if race is not None and race.goal_time_seconds and race.distance_km:
        prof = profile_for_race_goal(int(race.goal_time_seconds), float(race.distance_km))
    if prof is None:
        prof = interpolate_marathon_profile(DEFAULT_PROFILE_MARATHON_SECONDS)
    return float(prof["power_to_weight_w_per_kg"])


def get_strength(session, user_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    anchors = get_anchor_lifts(session, user_id)
    mass, _ = fetch_trend_mass(session, user_id, as_of)
    return compute_strength(fetch_lift_rows(session, user_id, as_of, anchors), anchors, mass, as_of)


def get_power_to_weight(session, user_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    mass, days = fetch_trend_mass(session, user_id, as_of)
    pool = axis_economy.easy_pool(axis_economy.fetch_rows(session, user_id, as_of), as_of)
    target = profile_target_w_per_kg(session, user_id, as_of)
    return compute_power_to_weight(pool, mass, days, target)


def _ex_name(ex: Any) -> str:
    if isinstance(ex, Mapping):
        return str(ex.get("name") or "")
    return str(getattr(ex, "name", "") or "")


def _ex_row(ex: Any, workout_date: date, workout_id: str) -> dict[str, Any]:
    get = ex.get if isinstance(ex, Mapping) else (lambda k: getattr(ex, k, None))
    return {
        "workout_date": workout_date,
        "name": _ex_name(ex),
        "sets_json": get("sets_json"),
        "weight_kg": get("weight_kg") if get("weight_kg") is not None else get("weight"),
        "reps": get("reps"),
        "sets": get("sets"),
        "workout_id": workout_id,
    }


def _lift_set_phrase(ex: Any) -> str:
    """e.g. '3 × 5 at 80 kg' from sets or summary columns."""
    sets = exercise_sets(ex)
    working = [s for s in sets if (s.get("type") or "working") != "warmup"]
    n = len(working) or (parse_reps(ex.get("sets") if isinstance(ex, Mapping) else getattr(ex, "sets", None)) or 0)
    if not working:
        get = ex.get if isinstance(ex, Mapping) else (lambda k: getattr(ex, k, None))
        kg = get("weight_kg") if get("weight_kg") is not None else get("weight")
        reps = parse_reps(get("reps"))
        sets_n = parse_reps(get("sets"))
        if kg and reps:
            prefix = f"{int(sets_n)} × " if sets_n else ""
            return f"{prefix}{int(reps)} at {int(round(float(kg)))} kg".strip()
        return ""
    best = max(working, key=lambda s: e1rm(s.get("weight", s.get("weight_kg")), s.get("reps")) or 0)
    kg = best.get("weight", best.get("weight_kg"))
    reps = parse_reps(best.get("reps"))
    try:
        kg_i = int(round(float(kg)))
    except (TypeError, ValueError):
        return ""
    n_sets = len(working)
    if reps:
        return f"{n_sets} × {int(reps)} at {kg_i} kg"
    return f"{n_sets} sets at {kg_i} kg"


def session_contribution(
    workout,
    as_of: date,
    *,
    session=None,
    exercises: Optional[list] = None,
    prior_rows: Optional[list] = None,
    anchors: Optional[list[dict[str, Any]]] = None,
    trend_mass_kg: Optional[float] = None,
) -> tuple[str, Optional[float], str]:
    """(status, delta, reason) for this session vs the strength axis."""
    wt = (getattr(workout, "workout_type", None) or "").lower()
    if "run" in wt:
        return "not_this_kind", None, "Strength moves with logged lifts and anchor tests."

    workout_id = str(getattr(workout, "id", "") or "")
    wdate = getattr(workout, "workout_date", None) or as_of
    this_ex = list(exercises or getattr(workout, "exercises", None) or [])

    if anchors is None and session is not None and getattr(workout, "user_id", None) is not None:
        try:
            anchors = get_anchor_lifts(session, workout.user_id)
        except Exception:
            anchors = None
    if not anchors:
        anchors = [dict(a) for a in DEFAULT_ANCHOR_LIFTS]

    matched = [ex for ex in this_ex if any(matches_anchor(_ex_name(ex), a) for a in anchors)]
    if this_ex and not matched:
        return "not_counted", None, "No logged lifts matching your anchors."
    if not this_ex and session is None and prior_rows is None:
        # Strength session with no exercises attached — still this kind of work.
        return "not_counted", None, "No logged lifts matching your anchors."

    rows: list[dict[str, Any]] = []
    if prior_rows is not None:
        rows.extend(prior_rows)
    elif session is not None and getattr(workout, "user_id", None) is not None:
        try:
            rows.extend(fetch_lift_rows(session, workout.user_id, as_of, anchors))
        except Exception:
            pass
    this_rows = [_ex_row(ex, wdate, workout_id) for ex in this_ex]
    # Prefer freshly passed exercises over a duplicate fetch of this workout.
    others = [r for r in rows if str(r.get("workout_id") or "") != workout_id]
    all_rows = others + this_rows

    if trend_mass_kg is None and session is not None and getattr(workout, "user_id", None) is not None:
        try:
            trend_mass_kg, _ = fetch_trend_mass(session, workout.user_id, as_of)
        except Exception:
            trend_mass_kg = None

    if not this_rows and not any(str(r.get("workout_id") or "") == workout_id for r in rows):
        return "not_counted", None, "No logged lifts matching your anchors."

    with_block = compute_strength(all_rows, anchors, trend_mass_kg, as_of)
    without_block = compute_strength(others, anchors, trend_mass_kg, as_of)
    with_score = with_block.get("score")
    without_score = without_block.get("score")
    if with_score is None:
        return "first", None, "First logged lifts toward Strength; more sessions are needed before it scores."

    best_ex = None
    best_e = None
    for ex in this_ex:
        v = best_set_e1rm(exercise_sets(ex))
        if v is not None and (best_e is None or v > best_e):
            best_e, best_ex = v, ex
    phrase = _lift_set_phrase(best_ex) if best_ex is not None else ""
    label = _ex_name(best_ex) if best_ex is not None else "This session"
    prev_kg = None
    if best_ex is not None:
        prev_working: list[float] = []
        for r in others:
            if any(matches_anchor(str(r.get("name") or ""), a) for a in anchors if matches_anchor(label, a)):
                for s in exercise_sets(r):
                    kg = s.get("weight", s.get("weight_kg"))
                    try:
                        prev_working.append(float(kg))
                    except (TypeError, ValueError):
                        pass
        if prev_working:
            prev_kg = int(round(max(prev_working)))

    if without_score is None:
        bit = f"{label} {phrase}".strip()
        return "first", None, f"{bit or 'This session'} is the first Strength input."

    delta = round(float(with_score) - float(without_score), 1)
    beat = f" beat your anchor ({prev_kg} kg)" if prev_kg else ""
    core = f"{label} {phrase}".strip() if phrase else label
    if delta > 0.05:
        return "raised", delta, f"{core}{beat} and raised the score by {delta}."
    if delta < -0.05:
        return "lowered", delta, f"{core} lowered the score by {abs(delta)}."
    return "counted", 0.0, f"{core} counted but did not move the Strength score."


AXIS_FUNCS = {"strength": get_strength, "power_to_weight": get_power_to_weight}
