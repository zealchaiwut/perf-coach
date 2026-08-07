"""Body composition — the guard that answers what weight alone cannot.

The question weight can't answer
--------------------------------
A falling scale is ambiguous: fat down is the goal, lean mass down is the failure
mode the whole program is built to avoid. A weekly bioimpedance reading resolves
the ambiguity, and that is its **only** job.

Bioimpedance is poor at absolute body fat (±5 percentage points) but acceptable
at *direction* under standardized conditions — same morning, post-bathroom,
pre-food, same weekday. So nothing here reports an absolute body-fat number as
authoritative, and nothing here carries a target:

- **No target, no goal line.** ``lean_mass_kg`` and ``body_fat_pct`` are trend
  series only. A body-composition target is out of scope by design — it is the
  leanness-maximalist framing that produces failed attempt number six.
- The output is a **guard**: is lean mass falling? If yes for long enough, the
  deficit pauses and the copy says eat more.

Smoothing
---------
Readings are weekly and noisy, so everything is a 4-week rolling mean. A single
bad reading shifts a 4-week mean by a quarter of its error instead of flipping a
verdict, and ``lean_mass_4wk_delta`` compares the most recent 4-week block to the
one before it rather than two individual readings.

Lean mass is **derived**, never stored::

    lean_mass_kg = weight_kg * (1 - body_fat_pct / 100)

so the two numbers can't drift apart in the database.
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta
from typing import Iterable, Optional
from backend.utils.time import today_bangkok

# Rolling window for every trend reported here. Four weekly readings is the
# fewest that can distinguish a direction from noise at bioimpedance's precision.
ROLLING_WEEKS = 4
# Consecutive falling blocks — REPORTED, no longer what the guard fires on.
# See LEAN_MASS_FALL_DELTA_KG and issue #1598.
LEAN_MASS_FALL_WEEKS = 3
# Lean-mass movement smaller than this is noise, not a fall. Bioimpedance can't
# resolve a quarter-kilo, and a guard that fires on noise gets ignored.
LEAN_MASS_NOISE_KG = 0.15

# Drop in the 4-week rolling MEAN, versus the previous 4-week block, that counts
# as lean mass genuinely falling.
#
# Chosen by simulation (#1598) rather than intuition. The previous rule —
# LEAN_MASS_FALL_WEEKS consecutive raw readings each falling by more than
# LEAN_MASS_NOISE_KG — was measured against a simulated athlete genuinely losing
# lean mass under realistic bioimpedance scatter, and had TWO independent
# defects:
#
#   1. The dead-band was applied per STEP, and the comparison was strict, so a
#      decline at or below 0.15 kg/week was invisible FOREVER — even with
#      perfect measurements. That is ~0.6 kg of lean mass a month, silently.
#   2. Any flat or up week reset the run to zero. Against a genuine decline with
#      ±1.0 point of body-fat scatter, the guard fired in roughly 4% of cases.
#
# Comparing 4-week block means fixes both: averaging four readings roughly halves
# the noise, and a cumulative drop cannot be hidden by one flat week. The module
# already smooths every other trend it reports this way — the guard was the one
# place reading raw consecutive values.
#
# Threshold trade-off, measured at ±1.0pt scatter over 3,000 simulated athletes
# per cell (false positive = fires on a FLAT athlete):
#
#     threshold | false+ | detects 0.15 kg/wk | detects 0.25 kg/wk
#       0.40 kg |  13.8% |       69.7%        |       95.2%
#       0.60 kg |   4.9% |       49.0%        |       85.7%
#   >>  0.70 kg |   2.1% |       38.3%        |       78.7%   <<
#       1.00 kg |   0.1% |       13.8%        |       49.1%
#
# 0.70 is deliberate. The costs are asymmetric — a false positive means eating
# a bit more for a week, a false negative means losing muscle — which argues for
# a low threshold. But the guard is evaluated EVERY week, so a real decline gets
# many chances to trip it, while a guard that cries wolf gets ignored and then
# protects nobody. 2% per check is roughly one spurious pause a year.
LEAN_MASS_FALL_DELTA_KG = 0.7


def derive_lean_mass_kg(weight_kg, body_fat_pct) -> Optional[float]:
    """Lean mass from a weigh-in plus its composition reading. None without both."""
    if weight_kg is None or body_fat_pct is None:
        return None
    try:
        w = float(weight_kg)
        bf = float(body_fat_pct)
    except (TypeError, ValueError):
        return None
    if w <= 0 or not (0 < bf < 100):
        return None
    return round(w * (1.0 - bf / 100.0), 2)


def derive_fat_mass_kg(weight_kg, body_fat_pct) -> Optional[float]:
    """Fat mass from a weigh-in plus its composition reading. None without both."""
    if weight_kg is None or body_fat_pct is None:
        return None
    try:
        w = float(weight_kg)
        bf = float(body_fat_pct)
    except (TypeError, ValueError):
        return None
    if w <= 0 or not (0 < bf < 100):
        return None
    return round(w * bf / 100.0, 2)


def _rolling_mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def compute_composition_trend(readings: Iterable[dict], today: _date) -> dict:
    """Summarise composition readings into trends and a lean-mass verdict.

    Parameters
    ----------
    readings:
        Dicts with ``date``, ``weight_kg`` and ``body_fat_pct``. Readings
        missing a body-fat value are ignored — a weigh-in without the scale
        can't say anything about composition. Order doesn't matter.
    today:
        Reference date; readings after it are ignored.

    Returns
    -------
    dict with keys:
        ``body_fat_pct_trend``   — 4-week rolling mean, or None
        ``lean_mass_kg_trend``   — 4-week rolling mean, or None
        ``fat_mass_kg_trend``    — 4-week rolling mean, or None
        ``lean_mass_4wk_delta``  — latest 4-week block minus the previous one
        ``fat_mass_4wk_delta``   — latest 4-week block minus the previous one
        ``lean_mass_falling_weeks`` — consecutive weekly blocks trending down
        ``readings_count``       — usable readings inside the trailing window
        ``readable``             — whether there is enough data to say anything
        ``readable_note``        — why not, when not
        ``readings``             — normalized [{date, body_fat_pct, lean_mass_kg}]

    There is deliberately no target, no goal, and no "on track" flag.
    """
    rows: list[dict] = []
    for r in readings or []:
        d = r.get("date")
        if d is None or d > today:
            continue
        lean = derive_lean_mass_kg(r.get("weight_kg"), r.get("body_fat_pct"))
        fat = derive_fat_mass_kg(r.get("weight_kg"), r.get("body_fat_pct"))
        if lean is None:
            continue
        rows.append({
            "date": d,
            "body_fat_pct": round(float(r["body_fat_pct"]), 1),
            "lean_mass_kg": lean,
            "fat_mass_kg": fat,
        })
    rows.sort(key=lambda r: r["date"])

    out = {
        "body_fat_pct_trend": None,
        "lean_mass_kg_trend": None,
        "fat_mass_kg_trend": None,
        "lean_mass_4wk_delta": None,
        "fat_mass_4wk_delta": None,
        "lean_mass_falling_weeks": 0,
        "lean_mass_falling": False,
        "readings_count": len(rows),
        "readable": False,
        "readable_note": None,
        "readings": [
            {
                "date": r["date"].isoformat(),
                "body_fat_pct": r["body_fat_pct"],
                "lean_mass_kg": r["lean_mass_kg"],
                "fat_mass_kg": r["fat_mass_kg"],
            }
            for r in rows
        ],
    }

    if not rows:
        out["readable_note"] = "no composition readings yet"
        return out

    window_start = today - _timedelta(weeks=ROLLING_WEEKS)
    recent = [r for r in rows if r["date"] > window_start]
    out["body_fat_pct_trend"] = _rolling_mean([r["body_fat_pct"] for r in recent])
    out["lean_mass_kg_trend"] = _rolling_mean([r["lean_mass_kg"] for r in recent])
    out["fat_mass_kg_trend"] = _rolling_mean([r["fat_mass_kg"] for r in recent])

    if len(rows) < ROLLING_WEEKS:
        out["readable_note"] = (
            f"{len(rows)} readings — {ROLLING_WEEKS} are needed before a "
            "direction means anything at this precision"
        )
        return out

    out["readable"] = True

    prev_start = today - _timedelta(weeks=ROLLING_WEEKS * 2)
    previous = [r for r in rows if prev_start < r["date"] <= window_start]
    prev_mean = _rolling_mean([r["lean_mass_kg"] for r in previous])
    prev_fat_mean = _rolling_mean([r["fat_mass_kg"] for r in previous])
    if prev_mean is not None and out["lean_mass_kg_trend"] is not None:
        out["lean_mass_4wk_delta"] = round(out["lean_mass_kg_trend"] - prev_mean, 2)
    if prev_fat_mean is not None and out["fat_mass_kg_trend"] is not None:
        out["fat_mass_4wk_delta"] = round(out["fat_mass_kg_trend"] - prev_fat_mean, 2)

    out["lean_mass_falling_weeks"] = _count_falling_weeks(rows)
    # What the deficit guard actually reads (#1598). The consecutive-raw-fall
    # count above is kept because it is reported and readable, but it could not
    # carry the guard: see LEAN_MASS_FALL_DELTA_KG for the measurements.
    delta = out["lean_mass_4wk_delta"]
    out["lean_mass_falling"] = delta is not None and delta <= -LEAN_MASS_FALL_DELTA_KG
    return out


def _count_falling_weeks(rows: list[dict]) -> int:
    """Consecutive most-recent weekly readings that fell from the one before.

    Walks backwards from the latest reading. A flat-within-noise step ends the
    run — the guard exists to catch a sustained decline, not a wobble.
    """
    falling = 0
    for newer, older in zip(reversed(rows), reversed(rows[:-1])):
        if newer["lean_mass_kg"] < older["lean_mass_kg"] - LEAN_MASS_NOISE_KG:
            falling += 1
        else:
            break
    return falling


def readings_for_user(db, user_id, today: Optional[_date] = None, weeks: int = 26) -> list[dict]:
    """Composition readings from ``weight_entries`` — those with a body-fat value."""
    from backend.models import WeightEntry

    today = today or today_bangkok()
    start = today - _timedelta(weeks=weeks)
    rows = (
        db.query(WeightEntry.entry_date, WeightEntry.weight_kg, WeightEntry.body_fat_pct)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= start,
            WeightEntry.entry_date <= today,
            WeightEntry.body_fat_pct.isnot(None),
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )
    return [
        {"date": r[0], "weight_kg": float(r[1]), "body_fat_pct": float(r[2])}
        for r in rows
    ]


def composition_for_user(db, user_id, today: Optional[_date] = None) -> dict:
    """``compute_composition_trend`` over a user's stored readings."""
    today = today or today_bangkok()
    return compute_composition_trend(readings_for_user(db, user_id, today), today)
