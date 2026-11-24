"""Economy axis score from Stryd running-dynamics (revamp P4-3).

Rules:

- Pool: easy runs of the last 28 days (at least half the duration in zone 2 or
  below, via ``workouts.zone2_minutes``) that carry a ``run_form_metrics`` row.
  Medians of leg spring stiffness, ground contact time and form power ratio.
- Sub-scores, each clamped 0..100:
    stiffness  = (lss - 6) / 6 x 100
    contact    = (300 - gct) / 90 x 100
    form power = (0.30 - fpr) / 0.10 x 100
- Score = rounded mean of the available sub-scores; at least 2 required, else
  never-measured.

The pool also feeds the power-to-weight axis (median ``power_w``, P4-4), so
``easy_pool`` is the single definition of "easy run with form data".
"""
from __future__ import annotations

import statistics
import uuid
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional

from backend.services.axis_spec import staleness_economy

POOL_WINDOW_DAYS = 28
MIN_EASY_FRACTION = 0.50
MIN_SUB_SCORES = 2

SUB_SCORE_KEYS = ("stiffness", "ground_contact", "form_power_ratio")


def _get(row: Any, key: str):
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _num(v) -> Optional[float]:
    return None if v is None else float(v)


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def stiffness_sub_score(lss: float) -> float:
    return _clamp((lss - 6.0) / 6.0 * 100.0)


def ground_contact_sub_score(gct: float) -> float:
    return _clamp((300.0 - gct) / 90.0 * 100.0)


def form_power_ratio_sub_score(fpr: float) -> float:
    return _clamp((0.30 - fpr) / 0.10 * 100.0)


def is_easy_run(run: Any) -> bool:
    """At least half the duration in zone 2 or below."""
    dur = _get(run, "duration_seconds")
    z2 = _get(run, "zone2_minutes")
    if not dur or z2 is None:
        return False
    return float(z2) * 60.0 >= MIN_EASY_FRACTION * float(dur)


def easy_pool(rows: Iterable[Any], as_of: date) -> list[Any]:
    """Rows (workout + form fields) inside the 28-day window that are easy runs.

    A row needs at least one form field (lss / gct / form_power_ratio / power_w)
    — "carries form data".
    """
    start = as_of - timedelta(days=POOL_WINDOW_DAYS - 1)
    out = []
    for r in rows:
        d = _get(r, "workout_date")
        if d is None or not (start <= d <= as_of):
            continue
        if not is_easy_run(r):
            continue
        if all(_get(r, k) is None for k in ("lss_kn_m", "gct_ms", "form_power_ratio", "power_w")):
            continue
        out.append(r)
    return out


def _median(rows: list[Any], key: str) -> Optional[float]:
    vals = [float(_get(r, key)) for r in rows if _get(r, key) is not None]
    return float(statistics.median(vals)) if vals else None


def median_power_w(pool: list[Any]) -> Optional[float]:
    return _median(pool, "power_w")


def compute_economy(rows: Iterable[Any], as_of: date) -> dict[str, Any]:
    pool = easy_pool(rows, as_of)
    with_form = [
        r for r in pool
        if any(_get(r, k) is not None for k in ("lss_kn_m", "gct_ms", "form_power_ratio"))
    ]
    lss = _median(pool, "lss_kn_m")
    gct = _median(pool, "gct_ms")
    fpr = _median(pool, "form_power_ratio")
    subs: dict[str, Optional[float]] = {
        "stiffness": stiffness_sub_score(lss) if lss is not None else None,
        "ground_contact": ground_contact_sub_score(gct) if gct is not None else None,
        "form_power_ratio": form_power_ratio_sub_score(fpr) if fpr is not None else None,
    }
    available = [v for v in subs.values() if v is not None]
    stale = staleness_economy(len(with_form))
    newest = max((_get(r, "workout_date") for r in pool), default=None)
    block: dict[str, Any] = {
        "axis": "economy",
        "score": None,
        "raw": {"lss_kn_m": lss, "gct_ms": gct, "form_power_ratio": fpr},
        "sub_scores": {k: (round(v, 1) if v is not None else None) for k, v in subs.items()},
        "n_runs": len(with_form),
        "never_measured": True,
        "stale": stale,
        "delta_28d": None,
        "anchor_date": newest.isoformat() if newest else None,
        "anchor_title": None,
    }
    if len(available) < MIN_SUB_SCORES:
        return block
    block["score"] = int(round(sum(available) / len(available)))
    block["never_measured"] = False
    return block


def fetch_rows(session, user_id: uuid.UUID, as_of: date) -> list[dict[str, Any]]:
    """Candidate run rows (workout joined to run_form_metrics) for the 28-day window."""
    from backend.models import RunFormMetrics as F, Workout as W

    start = as_of - timedelta(days=POOL_WINDOW_DAYS - 1)
    q = (
        session.query(W, F)
        .join(F, F.workout_id == W.id)
        .filter(
            W.user_id == user_id,
            W.workout_type.ilike("run"),
            W.workout_date >= start,
            W.workout_date <= as_of,
        )
    )
    out = []
    for w, f in q.all():
        out.append({
            "workout_id": str(w.id),
            "workout_date": w.workout_date,
            "name": w.name,
            "duration_seconds": w.duration_seconds,
            "zone2_minutes": w.zone2_minutes,
            "lss_kn_m": _num(f.lss_kn_m),
            "gct_ms": _num(f.gct_ms),
            "form_power_ratio": _num(f.form_power_ratio),
            "power_w": _num(f.power_w),
        })
    return out


def get_economy(session, user_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    return compute_economy(fetch_rows(session, user_id, as_of), as_of)


def session_contribution(workout, as_of: date, *, session=None) -> tuple[str, Optional[float], str]:
    """(status, delta, reason) for this workout vs the economy easy-run pool."""
    wt = (getattr(workout, "workout_type", None) or "").lower()
    if "run" not in wt:
        return (
            "not_this_kind",
            None,
            "Plyo and calf work help it over weeks, not in one session.",
        )
    if not is_easy_run(workout):
        return "not_counted", None, "Economy uses easy runs with Stryd form data."
    wid = str(getattr(workout, "id", "") or "")
    rows = None
    if session is not None and getattr(workout, "user_id", None) is not None:
        try:
            rows = fetch_rows(session, workout.user_id, as_of)
        except Exception:
            rows = None
    if rows is None:
        # In the input pool by the easy-run rule, but no form-pool delta available.
        return "counted", 0.0, "Easy run; in the 28-day economy pool."
    in_pool = any(str(r.get("workout_id")) == wid for r in rows)
    if not in_pool:
        return "not_counted", None, "Economy uses easy runs with Stryd form data."
    with_score = compute_economy(rows, as_of).get("score")
    without = [r for r in rows if str(r.get("workout_id")) != wid]
    without_score = compute_economy(without, as_of).get("score")
    if with_score is None:
        return "first", None, "First easy run with form data; Economy needs more before it scores."
    if without_score is None:
        return "first", None, "First easy run with form data; Economy needs more before it scores."
    delta = round(float(with_score) - float(without_score), 1)
    if delta > 0.05:
        return "raised", delta, f"Easy-run form data raised the score by {delta}."
    if delta < -0.05:
        return "lowered", delta, f"Easy-run form data lowered the score by {abs(delta)}."
    return "counted", 0.0, "Easy run with form data; in the 28-day economy pool."


AXIS_FUNCS = {"economy": get_economy}
