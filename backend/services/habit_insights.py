"""Habit-outcome correlation insight builder.

Pure function — no DB access. Caller supplies all data.
"""

from __future__ import annotations

import os
import statistics
from typing import Any

from backend.services.habit_outcome_alignment import align_habit_and_outcome

# ---------------------------------------------------------------------------
# Configuration helpers — threshold must never be a hardcoded literal
# ---------------------------------------------------------------------------

def _read_min_sample_size() -> int:
    """Return minimum overlapping-day threshold from env; default 7."""
    raw = os.environ.get("HABIT_INSIGHTS_MIN_SAMPLE_SIZE", "7")
    try:
        return max(2, int(raw))
    except (ValueError, TypeError):
        return 7


# Internal confidence threshold (minimum |r| to surface an insight)
_MIN_ABS_R: float = 0.1

# Lag values (in days) to try for each habit-outcome pair
_LAG_OPTIONS: tuple[int, ...] = (0, 1, 2)

# Outcome fields sourced from DailyMetric that this builder knows about
OUTCOME_FIELDS: tuple[str, ...] = ("energy", "mood", "sleep_quality", "hrv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _outcome_label(outcome_name: str) -> str:
    return outcome_name.replace("_", " ").title()


def _generate_line(
    habit_name: str,
    outcome_name: str,
    coefficient: float,
    lag_days: int,
) -> str:
    """Return a plain-English sentence describing the insight."""
    direction = "higher" if coefficient >= 0 else "lower"
    label = _outcome_label(outcome_name)
    if lag_days == 0:
        return (
            f"Logging '{habit_name}' is associated with {direction} "
            f"'{label}' scores on the same day."
        )
    day_word = "day" if lag_days == 1 else "days"
    return (
        f"Logging '{habit_name}' is associated with {direction} "
        f"'{label}' scores {lag_days} {day_word} later."
    )


def _pearson(x_seq: list[float], y_seq: list[float]) -> float:
    """Return Pearson r using stdlib statistics.correlation (Python 3.10+)."""
    return statistics.correlation(x_seq, y_seq)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_insights(
    habits: list[Any],
    habit_logs_by_habit: dict[str, dict[str, float]],
    outcome_series_by_name: dict[str, dict[str, float]],
    min_sample_size: int | None = None,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Compute habit-outcome correlations and return the insight triple.

    All DB access is the caller's responsibility; this function is pure.

    Parameters
    ----------
    habits:
        Sequence of habit objects with ``.id`` (UUID) and ``.name`` (str).
    habit_logs_by_habit:
        Mapping of str(habit_id) -> {date_str: numeric value}.
        Boolean completion logs should be converted to 1.0/0.0 by the caller.
    outcome_series_by_name:
        Mapping of outcome_name -> {date_str: float}.
    min_sample_size:
        Override for the configured threshold. Reads the
        ``HABIT_INSIGHTS_MIN_SAMPLE_SIZE`` env var when ``None``.

    Returns
    -------
    (insights, building, reason)
        insights: list of insight dicts (empty when building=True).
        building: True when data is insufficient.
        reason: human-readable explanation when building=True; None otherwise.
    """
    if min_sample_size is None:
        min_sample_size = _read_min_sample_size()

    # Determine global overlap: days where ANY habit log AND ANY outcome exist
    all_habit_dates: set[str] = set()
    for logs in habit_logs_by_habit.values():
        if logs:
            all_habit_dates.update(logs.keys())

    all_outcome_dates: set[str] = set()
    for series in outcome_series_by_name.values():
        if series:
            all_outcome_dates.update(series.keys())

    overlap_count = len(all_habit_dates & all_outcome_dates)

    if overlap_count < min_sample_size:
        if not all_habit_dates:
            reason: str = "Not enough habit logs yet."
        elif not all_outcome_dates:
            reason = "Not enough outcome data yet."
        else:
            reason = (
                f"Not enough overlapping days yet "
                f"({overlap_count} of {min_sample_size} required)."
            )
        return [], True, reason

    # Compute the best (highest |r|) correlation per (habit, outcome) pair
    insights: list[dict[str, Any]] = []

    for habit in habits:
        habit_id_str = str(habit.id)
        logs = habit_logs_by_habit.get(habit_id_str) or {}
        if not logs:
            continue

        for outcome_name, outcome_series in outcome_series_by_name.items():
            if not outcome_series:
                continue

            best: dict[str, Any] | None = None

            for lag in _LAG_OPTIONS:
                pairs, _ = align_habit_and_outcome(logs, outcome_series, lag)
                n = len(pairs)
                if n < min_sample_size:
                    continue

                x = [float(p["habit_value"]) for p in pairs]
                y = [float(p["outcome_value"]) for p in pairs]

                # Pearson requires variance in both series
                if len(set(x)) < 2 or len(set(y)) < 2:
                    continue

                try:
                    r = _pearson(x, y)
                except statistics.StatisticsError:
                    continue

                # Clamp to [-1, 1] for guaranteed serialisation safety
                r = max(-1.0, min(1.0, r))

                if abs(r) < _MIN_ABS_R:
                    continue

                if best is None or abs(r) > abs(best["coefficient"]):
                    best = {
                        "habit_id": habit_id_str,
                        "habit_name": habit.name,
                        "outcome_name": outcome_name,
                        "coefficient": round(r, 4),
                        "sample_size": n,
                        "lag_days": lag,
                        "line": _generate_line(
                            habit.name, outcome_name, r, lag
                        ),
                    }

            if best is not None:
                insights.append(best)

    return insights, False, None
