"""Canonical weight rate — OLS on EWMA with coverage gates for all consumers.

Single source for the weight tab header, current-weight card, and cut review
``actual_rate``. Uses stricter readability thresholds (70% coverage, 21 days)
than coach_export's ``compute_trend_rate`` defaults.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Optional

from backend.services.weight_ewma import compute_ewma
from backend.services.weight_trend_rate import compute_trend_rate
from backend.utils.time import today_bangkok

COVERAGE_THRESHOLD = 70  # single named constant
MIN_N_DAYS = 21
DEFAULT_WINDOW_DAYS = 30
EWMA_ALPHA = 0.18


def _load_weight_entries(db, user_id, as_of: _date) -> list[dict]:
    from backend.models import WeightEntry

    rows = (
        db.query(WeightEntry)
        .filter(WeightEntry.user_id == user_id, WeightEntry.entry_date <= as_of)
        .order_by(WeightEntry.entry_date.asc(), WeightEntry.entry_time.asc())
        .all()
    )
    by_day: dict[_date, float] = {}
    for r in rows:
        by_day[r.entry_date] = float(r.weight_kg)
    return [{"date": d, "weight_kg": w} for d, w in sorted(by_day.items())]


def _active_target_rate(db, user_id) -> Optional[float]:
    from backend.models import WeightTarget

    plan = (
        db.query(WeightTarget)
        .filter(WeightTarget.user_id == user_id, WeightTarget.status == "active")
        .first()
    )
    if plan is None or plan.target_rate_kg_per_week is None:
        return None
    return float(plan.target_rate_kg_per_week)


def weight_stats(
    db,
    user_id,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    as_of: Optional[_date] = None,
    needed_rate_kg_wk: Optional[float] = None,
) -> dict:
    """OLS-on-EWMA rate with CI and readability for the weight tab consumers."""
    as_of = as_of or today_bangkok()
    entries = _load_weight_entries(db, user_id, as_of)
    ewma = compute_ewma(entries, alpha=EWMA_ALPHA) if entries else []

    # Window-proportional minimum: ~70% of window length, floored at 3 (OLS
    # needs n >= 3), capped at MIN_N_DAYS so callers with >=30-day windows keep
    # the strict 21-entry gate. Without this, every window_days call would pass
    # min_entries=21 — a 7-day window can never satisfy 21, permanently blocking
    # consecutive_weeks_behind from incrementing in cut_review.py (issue #1697).
    _min_entries = max(3, min(MIN_N_DAYS, round(window_days * COVERAGE_THRESHOLD / 100)))

    trend = compute_trend_rate(
        entries,
        as_of,
        window_days=window_days,
        ewma_values=ewma,
        min_coverage_pct=COVERAGE_THRESHOLD,
        min_entries=_min_entries,
    )

    if needed_rate_kg_wk is None:
        needed_rate_kg_wk = _active_target_rate(db, user_id)

    return {
        "trend_kg": trend["trend_kg"],
        "rate_kg_wk": trend["rate_kg_per_week"] if trend["readable"] else None,
        "ci_kg_wk": trend["ci_kg_per_week"] if trend["readable"] else None,
        "state": trend["state"] if trend["readable"] else "unknown",
        "readable": trend["readable"],
        "gated": not trend["readable"],
        "gate_reason": (
            None if trend["readable"]
            else (trend["readable_note"] or "insufficient_coverage")
        ),
        "days_needed": (
            0 if trend["readable"]
            else max(0, _min_entries - int(trend["entries_used"] or 0))
        ),
        "coverage_pct": trend["coverage_pct"],
        "needed_rate_kg_wk": needed_rate_kg_wk,
        "entries_used": trend["entries_used"],
        "window_days": window_days,
        "last_weigh_in": trend["last_weigh_in"],
        "readable_note": trend["readable_note"],
    }
