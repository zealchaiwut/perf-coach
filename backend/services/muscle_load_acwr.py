"""Per-muscle-group acute/chronic load and ACWR computation (issue #1380).

Mirrors the whole-body ACWR machinery in backend/services/acwr.py at muscle
granularity. Reads from muscle_load_daily (written by issues #1367 / #1379).

Math
----
Acute: rolling 7-day sum (most recent 7 days inclusive of today).
Chronic: mean of 4 prior non-overlapping 7-day windows (days −35…−8 from today,
same "uncoupled" variant as acwr.py so the acute window is excluded).
ACWR = acute / chronic when chronic >= CHRONIC_FLOOR, else None.

Classification constants (documented in docs/calculations/muscle-load.md):
  overused   acwr > 1.5
  elevated   1.3 < acwr <= 1.5
  balanced   0.8 <= acwr <= 1.3
  detraining acwr < 0.8 with nonzero chronic
  untrained  chronic near-zero for priority group (calf, hamstring, glute, hip)
  inactive   chronic near-zero for non-priority group
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date, timedelta as _td
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.db import engine

# ── Classification constants ───────────────────────────────────────────────────

CHRONIC_FLOOR: float = 5.0
"""Weekly chronic average below this is treated as zero; ACWR is undefined."""

OVERUSED_BOUND: float = 1.5
"""acwr > OVERUSED_BOUND → overused (mirrors acwr.HIGH_BOUND)."""

ELEVATED_BOUND: float = 1.3
"""ELEVATED_BOUND < acwr <= OVERUSED_BOUND → elevated (mirrors acwr.UPPER_BOUND)."""

DETRAINING_BOUND: float = 0.8
"""acwr < DETRAINING_BOUND with nonzero chronic → detraining (mirrors acwr.LOWER_BOUND)."""

# Lower-body focus groups: when chronic is near zero these are flagged as
# untrained rather than merely inactive.
PRIORITY_GROUPS: frozenset[str] = frozenset({"calf", "hamstring", "glute", "hip"})

ALL_GROUPS: tuple[str, ...] = (
    "calf", "quad", "hamstring", "glute", "hip",
    "core", "back", "shoulder", "chest", "arm", "other",
)

# ── Body-area → muscle-group mapping for injury tagging ───────────────────────
# body_area values in InjuryLog are free-text; common anatomical terms mapped
# to canonical groups. Lowercase keys, case-insensitive at lookup time.

BODY_AREA_TO_GROUP: dict[str, str] = {
    "calf": "calf",
    "calves": "calf",
    "ankle": "calf",
    "achilles": "calf",
    "shin": "calf",
    "tibialis": "calf",
    "hamstring": "hamstring",
    "hamstrings": "hamstring",
    "quad": "quad",
    "quads": "quad",
    "quadriceps": "quad",
    "knee": "quad",
    "it band": "quad",
    "iliotibial": "quad",
    "glute": "glute",
    "glutes": "glute",
    "gluteus": "glute",
    "hip": "hip",
    "groin": "hip",
    "hip flexor": "hip",
    "hip flexors": "hip",
    "core": "core",
    "abs": "core",
    "abdominal": "core",
    "oblique": "core",
    "back": "back",
    "lower back": "back",
    "lumbar": "back",
    "erector": "back",
    "lat": "back",
    "shoulder": "shoulder",
    "shoulders": "shoulder",
    "rotator cuff": "shoulder",
    "deltoid": "shoulder",
    "chest": "chest",
    "pec": "chest",
    "pectoral": "chest",
    "arm": "arm",
    "bicep": "arm",
    "biceps": "arm",
    "tricep": "arm",
    "triceps": "arm",
    "elbow": "arm",
    "wrist": "arm",
    "forearm": "arm",
    "forearms": "arm",
}


# ── Classification ordering ───────────────────────────────────────────────────

_CLASSIFICATION_RANK: dict[str, int] = {
    "overused": 0,
    "elevated": 1,
    "balanced": 2,
    "detraining": 3,
    "untrained": 4,
    "inactive": 5,
}


def classification_sort_key(classification: str, injured: bool = False) -> tuple:
    """Return a (rank, not_injured) sort key for worst-first ordering.

    Lower tuple → worse (sorts first). Within the same classification, injured
    groups sort before uninjured ones.
    """
    rank = _CLASSIFICATION_RANK.get(classification, 99)
    return (rank, 0 if injured else 1)


def sort_groups_worst_first(groups: dict) -> list:
    """Return a list of group dicts ordered worst-first.

    Each dict is the per-group stats dict from compute() with an added ``group``
    key holding the canonical group name.
    """
    items = []
    for group, stats in groups.items():
        item = dict(stats)
        item["group"] = group
        items.append(item)
    items.sort(key=lambda x: classification_sort_key(
        x.get("classification", "inactive"), bool(x.get("injured", False))
    ))
    return items


# ── Pure functions (no DB access) ─────────────────────────────────────────────

def compute_acute_chronic(daily_totals: list[float]) -> tuple[float, float]:
    """Given a 35-element list (oldest first, today last), return (acute_7d, chronic_28d).

    Matches acwr.py's convention exactly:
      acute = sum(last 7 elements)
      chronic = mean of 4 prior 7-element windows

    If the list has fewer than 35 elements it is zero-padded on the left.
    """
    n = len(daily_totals)
    if n < 35:
        daily_totals = [0.0] * (35 - n) + list(daily_totals)

    vals = daily_totals

    acute = sum(vals[-7:])

    prior_week_windows = [
        vals[-35:-28],
        vals[-28:-21],
        vals[-21:-14],
        vals[-14:-7],
    ]
    prior_totals = [sum(w) for w in prior_week_windows if w]
    chronic = sum(prior_totals) / len(prior_totals) if prior_totals else 0.0

    return acute, chronic


def classify_group(
    group: str,
    chronic: float,
    acwr: Optional[float],
) -> str:
    """Classify a muscle group.

    Returns one of: overused, elevated, balanced, detraining, untrained, inactive.
    """
    if chronic < CHRONIC_FLOOR:
        return "untrained" if group in PRIORITY_GROUPS else "inactive"
    if acwr is None:
        # chronic >= CHRONIC_FLOOR but ACWR is null: treat as inactive
        return "inactive"
    if acwr > OVERUSED_BOUND:
        return "overused"
    if acwr > ELEVATED_BOUND:
        return "elevated"
    if acwr >= DETRAINING_BOUND:
        return "balanced"
    return "detraining"


def body_area_to_group(area: str) -> Optional[str]:
    """Map an injury body_area string to a canonical muscle group, or None."""
    return BODY_AREA_TO_GROUP.get(area.strip().lower())


# ── DB query helpers ───────────────────────────────────────────────────────────

def _fetch_unclassified(
    user_id: _uuid.UUID,
    window_start: _date,
    window_end: _date,
    db: Session,
) -> list[str]:
    """Return exercise names used in the window but absent from exercise_catalog."""
    from backend.models import ExerciseCatalog, StrengthSession, Workout, WorkoutExercise

    workout_ids_q = (
        db.query(Workout.id)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= window_start,
            Workout.workout_date <= window_end,
            Workout.workout_type == "strength",
        )
        .subquery()
    )

    wo_names: set[str] = {
        row[0].strip().lower()
        for row in db.query(WorkoutExercise.name)
        .filter(WorkoutExercise.workout_id.in_(workout_ids_q))
        .all()
        if row[0]
    }

    ss_names: set[str] = {
        row[0].strip().lower()
        for row in db.query(StrengthSession.exercise_name)
        .filter(
            StrengthSession.user_id == user_id,
            StrengthSession.session_date >= window_start,
            StrengthSession.session_date <= window_end,
        )
        .all()
        if row[0]
    }

    all_names = wo_names | ss_names
    if not all_names:
        return []

    catalog_names: set[str] = {
        row[0]
        for row in db.query(ExerciseCatalog.name)
        .filter(ExerciseCatalog.name.in_(list(all_names)))
        .all()
    }

    return sorted(all_names - catalog_names)


# ── Main computation ───────────────────────────────────────────────────────────

def compute(
    user_id: _uuid.UUID,
    as_of_date: _date,
    weeks: int = 8,
) -> dict:
    """Compute per-muscle-group load stats for the session user.

    Parameters
    ----------
    user_id:  Session user's UUID.
    as_of_date: Reference date (usually today); acute/chronic computed relative to this.
    weeks:    Number of weeks for the charting series (default 8).

    Returns
    -------
    dict with keys:
      as_of          ISO date string
      groups         per-group dict (acute_7d, chronic_28d, acwr, classification,
                     injured, source_breakdown)
      weekly_series  list of {week_start, week_end, groups} entries (length = weeks)
      unclassified   list of exercise names without a catalog entry
    """
    from backend.models import InjuryLog, MuscleLoadDaily

    # Fetch enough history for weekly series + 35-day stats window
    lookback_days = max(35, weeks * 7)
    window_start = as_of_date - _td(days=lookback_days - 1)

    with Session(engine) as db:
        rows = (
            db.query(MuscleLoadDaily)
            .filter(
                MuscleLoadDaily.user_id == user_id,
                MuscleLoadDaily.load_date >= window_start,
                MuscleLoadDaily.load_date <= as_of_date,
            )
            .all()
        )

        active_injuries = (
            db.query(InjuryLog)
            .filter(
                InjuryLog.user_id == user_id,
                InjuryLog.started_on <= as_of_date,
                or_(
                    InjuryLog.ended_on.is_(None),
                    InjuryLog.ended_on >= as_of_date,
                ),
            )
            .all()
        )

        unclassified = _fetch_unclassified(user_id, window_start, as_of_date, db)

    # Build injured groups set from active injuries
    injured_groups: set[str] = set()
    for inj in active_injuries:
        if inj.body_area:
            grp = body_area_to_group(inj.body_area)
            if grp:
                injured_groups.add(grp)

    # Build daily lookup: {date: {group: {source: load}}}
    daily: dict[_date, dict[str, dict[str, float]]] = {}
    for row in rows:
        d = row.load_date
        g = row.muscle_group
        s = row.source
        v = float(row.load)
        day_dict = daily.setdefault(d, {})
        group_dict = day_dict.setdefault(g, {})
        group_dict[s] = group_dict.get(s, 0.0) + v

    # Per-group current stats
    groups_out: dict[str, dict] = {}
    for group in ALL_GROUPS:
        # Build 35-element series (oldest first) aligned to as_of_date
        series_35 = [
            sum(daily.get(as_of_date - _td(days=i), {}).get(group, {}).values())
            for i in range(34, -1, -1)
        ]

        acute, chronic = compute_acute_chronic(series_35)
        acwr = acute / chronic if chronic >= CHRONIC_FLOOR else None
        classification = classify_group(group, chronic, acwr)

        # Per-source breakdown within the chronic window (prior 28 days: days -34 to -7)
        source_totals: dict[str, float] = {}
        for i in range(34, 6, -1):
            day = as_of_date - _td(days=i)
            for src, v in daily.get(day, {}).get(group, {}).items():
                source_totals[src] = source_totals.get(src, 0.0) + v
        total_src = sum(source_totals.values())
        if total_src > 0:
            source_breakdown = {s: round(v / total_src, 4) for s, v in source_totals.items()}
        else:
            source_breakdown = {}

        groups_out[group] = {
            "acute_7d": round(acute, 4),
            "chronic_28d": round(chronic, 4),
            "acwr": round(acwr, 4) if acwr is not None else None,
            "classification": classification,
            "injured": group in injured_groups,
            "source_breakdown": source_breakdown,
        }

    # Weekly series (N entries, most recent last)
    weekly_series = []
    for w in range(weeks - 1, -1, -1):
        week_end = as_of_date - _td(days=w * 7)
        week_start = week_end - _td(days=6)
        week_groups: dict[str, float] = {}
        for group in ALL_GROUPS:
            total = sum(
                sum(daily.get(week_start + _td(days=i), {}).get(group, {}).values())
                for i in range(7)
            )
            if total > 0:
                week_groups[group] = round(total, 4)
        weekly_series.append({
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "groups": week_groups,
        })

    return {
        "as_of": as_of_date.isoformat(),
        "groups": groups_out,
        "weekly_series": weekly_series,
        "unclassified": unclassified,
    }
