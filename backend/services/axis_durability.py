"""Durability axis score from long-run aerobic decoupling (revamp P4-2).

Rules (docs/revamp/SPEC.md, appendix «Performance axes»):

- Qualifying run: >= 90 minutes, has ``workouts.decoupling_percent``, and at
  least 60 percent of its time in zones 1 and 2.
- Raw value: median decoupling of the last 4 qualifying runs (2 or 3 when that
  is all there is). Fewer than 2 qualifying runs -> never-measured.
- Score = clamp(100 - (median - 3) x 8, 0, 100), rounded to an integer.

Zone 1+2 share: ``workouts.easy_minutes`` (HR at or below the Z2 ceiling) over
``duration_seconds``, falling back to ``zone2_minutes`` when ``easy_minutes`` is
unset. A run with neither field cannot be shown to be easy and does not qualify.

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
    """Share of the run spent in Z1+Z2 (easy_minutes, else zone2_minutes) / duration."""
    dur = _get(run, "duration_seconds")
    easy = _get(run, "easy_minutes")
    if easy is None:
        easy = _get(run, "zone2_minutes")
    if not dur or easy is None:
        return None
    return (float(easy) * 60.0) / float(dur)


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


def session_contribution(workout, as_of: date, *, session=None) -> tuple[str, Optional[float], str]:
    """(status, delta, reason) for this workout vs the durability long-run pool."""
    wt = (getattr(workout, "workout_type", None) or "").lower()
    if "run" not in wt:
        return "not_this_kind", None, "Durability needs long easy runs."
    dur = _get(workout, "duration_seconds")
    mins = int(round(float(dur) / 60.0)) if dur else 0
    if dur is None or int(dur) < MIN_DURATION_SECONDS:
        return (
            "not_counted",
            None,
            f"Needs an easy run of 90 min or more; this one was {mins} min.",
        )
    if not is_qualifying_run(workout):
        return (
            "not_counted",
            None,
            f"Needs an easy run of 90 min or more with decoupling data; this one was {mins} min.",
        )
    runs = []
    if session is not None and getattr(workout, "user_id", None) is not None:
        try:
            runs = list(fetch_runs(session, workout.user_id, as_of))
        except Exception:
            runs = []
    wid = str(getattr(workout, "id", "") or "")

    def _id(r):
        return str(_get(r, "id") or _get(r, "workout_id") or "")

    if not any(_id(r) == wid for r in runs):
        runs = [workout] + runs
    with_block = compute_durability(runs, as_of)
    without = [r for r in runs if _id(r) != wid]
    without_block = compute_durability(without, as_of)
    if with_block.get("score") is None:
        return "first", None, "First qualifying long run; Durability needs one more before it scores."
    if without_block.get("score") is None:
        return "first", None, "First qualifying long run; Durability needs one more before it scores."
    delta = round(float(with_block["score"]) - float(without_block["score"]), 1)
    if delta > 0.05:
        return "raised", delta, f"This long run raised Durability by {delta}."
    if delta < -0.05:
        return "lowered", delta, f"This long run lowered Durability by {abs(delta)}."
    return "counted", 0.0, "Qualifying long run; in the Durability pool."


AXIS_FUNCS = {"durability": get_durability}
