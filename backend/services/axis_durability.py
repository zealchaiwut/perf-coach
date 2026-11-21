"""Durability axis score from long-run aerobic decoupling (revamp P4-2).

Rules (docs/revamp/SPEC.md, appendix «Performance axes»):

- Qualifying run: >= 90 minutes, has ``workouts.decoupling_percent``, and at
  least 60 percent of its time in zones 1 and 2.
- Raw value: median decoupling of the last 4 qualifying runs (2 or 3 when that
  is all there is). Fewer than 2 qualifying runs -> never-measured.
- Score = clamp(100 - (median - 3) x 8, 0, 100), rounded to an integer.

Zone 1+2 share: the per-run field ``workouts.zone2_minutes`` over
``duration_seconds``. (The lap-based intensity-distribution endpoint needs a
per-session split query; the stored per-run minutes keep this reader a single
indexed query and match what the Z2 habit autofill already trusts.) A run with
no ``zone2_minutes`` cannot be shown to be easy and does not qualify.

Pure helpers + one thin DB fetch; no HTTP, no LLM.
"""
from __future__ import annotations

import statistics
import uuid
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional

from backend.services.axis_spec import staleness_durability

MIN_DURATION_SECONDS = 90 * 60
MIN_EASY_FRACTION = 0.60
MAX_RUNS = 4
MIN_RUNS = 2
DECOUPLING_FLOOR_PCT = 3.0
PENALTY_PER_PCT = 8.0
STALE_WINDOW_DAYS = 45


def _get(run: Any, key: str):
    if isinstance(run, Mapping):
        return run.get(key)
    return getattr(run, key, None)


def easy_fraction(run: Any) -> Optional[float]:
    """Share of the run spent in zones 1-2 (zone2_minutes / duration), or None."""
    dur = _get(run, "duration_seconds")
    z2 = _get(run, "zone2_minutes")
    if not dur or z2 is None:
        return None
    return (float(z2) * 60.0) / float(dur)


def is_qualifying_run(run: Any) -> bool:
    """>= 90 min, a decoupling value, and >= 60% of time in zones 1-2."""
    dur = _get(run, "duration_seconds")
    if dur is None or int(dur) < MIN_DURATION_SECONDS:
        return False
    if _get(run, "decoupling_percent") is None:
        return False
    frac = easy_fraction(run)
    return frac is not None and frac >= MIN_EASY_FRACTION


def durability_score_from_median(median_decoupling: float) -> int:
    raw = 100.0 - (float(median_decoupling) - DECOUPLING_FLOOR_PCT) * PENALTY_PER_PCT
    return int(round(max(0.0, min(100.0, raw))))


def compute_durability(runs: Iterable[Any], as_of: date) -> dict[str, Any]:
    """Build the durability axis block from candidate run workouts.

    ``runs`` may contain any run workouts (dicts or ORM rows) with
    ``workout_date``, ``duration_seconds``, ``decoupling_percent`` and
    ``zone2_minutes``; non-qualifying ones are filtered here.
    """
    qualifying = sorted(
        (r for r in runs if is_qualifying_run(r) and _get(r, "workout_date") <= as_of),
        key=lambda r: _get(r, "workout_date"),
        reverse=True,
    )
    in_window = [
        r for r in qualifying
        if (as_of - _get(r, "workout_date")).days <= STALE_WINDOW_DAYS
    ]
    stale = staleness_durability(len(in_window))
    used = qualifying[:MAX_RUNS]
    base: dict[str, Any] = {
        "axis": "durability",
        "score": None,
        "raw": None,
        "unit": "decoupling_pct",
        "n_runs": len(used),
        "never_measured": True,
        "stale": stale,
        "delta_28d": None,
        "anchor_date": None,
        "anchor_title": None,
    }
    if len(used) < MIN_RUNS:
        return base
    median = float(statistics.median(float(_get(r, "decoupling_percent")) for r in used))
    newest = used[0]
    wd = _get(newest, "workout_date")
    base.update(
        score=durability_score_from_median(median),
        raw=round(median, 2),
        never_measured=False,
        anchor_date=wd.isoformat() if hasattr(wd, "isoformat") else str(wd),
        anchor_title=_get(newest, "name"),
    )
    return base


def fetch_runs(session, user_id: uuid.UUID, as_of: date) -> list[Any]:
    """Recent long candidate runs (cheap SQL pre-filter; rules applied in Python)."""
    from backend.models import Workout

    return (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type.ilike("run"),
            Workout.workout_date <= as_of,
            Workout.duration_seconds >= MIN_DURATION_SECONDS,
            Workout.decoupling_percent.isnot(None),
        )
        .order_by(Workout.workout_date.desc())
        .limit(40)
        .all()
    )


def get_durability(session, user_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    return compute_durability(fetch_runs(session, user_id, as_of), as_of)


AXIS_FUNCS = {"durability": get_durability}
