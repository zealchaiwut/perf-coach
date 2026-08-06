"""Weight-trend rate with a confidence interval — the honest "am I losing?" answer.

Why this exists
---------------
``weight_plan.compute_weight_status`` answers "am I on pace for my target"
(plan-relative). ``weight_ewma_rate`` answers "what percent of bodyweight did
the EWMA move over one window" (a two-point difference, no uncertainty). Neither
can say whether an observed rate is *distinguishable from flat*, and a coach
message that calls a 0.05 kg/week wobble "losing weight" is wrong in a way the
athlete cannot check.

So: fit an ordinary least-squares line to the EWMA trend over the window, and
report the slope WITH its 95% confidence interval. When the interval contains
zero, the state is ``flat`` — the data does not support a direction.

Math
----
Given EWMA points ``(t_i, y_i)`` where ``t_i`` is days since the window start
and ``y_i`` is the smoothed weight in kg::

    slope_kg_per_day = Sxy / Sxx
    residual_var     = SSE / (n - 2)
    se_slope         = sqrt(residual_var / Sxx)
    ci_half_width    = T_CRIT_95 * se_slope          # kg/day
    rate_kg_per_week = slope_kg_per_day * 7

``T_CRIT_95`` is a fixed 1.96 (normal approximation) rather than a per-n
Student-t table: with the 45-day default window n is large enough that the
difference is under the rounding we report, and hard-coding a table is the kind
of precision this signal does not have.

Readability
-----------
A slope fitted through three weigh-ins in 45 days is arithmetic, not evidence.
``readable`` is False when coverage (distinct weigh-in days / window days) is
below ``MIN_COVERAGE_PCT`` or fewer than ``MIN_ENTRIES`` entries exist. Callers
must not present the rate as a fact when ``readable`` is False — that is the
whole point of the flag.

Worked example
--------------
Window 45 days, 30 weigh-ins, EWMA falling 78.4 → 77.5 kg roughly linearly:
slope ≈ −0.020 kg/day → ``rate_kg_per_week`` ≈ −0.14; with tight residuals the
CI half-width is ≈ 0.03 kg/week, so the interval (−0.17, −0.11) excludes zero
and ``state`` is ``losing``. Halve the entries and widen the scatter and the
same central rate can produce an interval spanning zero → ``flat``.
"""
from __future__ import annotations

import math
from datetime import date as _date, timedelta as _timedelta
from typing import Optional

DEFAULT_WINDOW_DAYS: int = 45
# Below this fraction of days covered by a weigh-in the fit is not reportable.
MIN_COVERAGE_PCT: float = 40.0
# Fewer than three points cannot produce a residual variance at all (n - 2 <= 0).
MIN_ENTRIES: int = 5
# Normal approximation to the two-sided 95% critical value — see module docstring.
T_CRIT_95: float = 1.96
# Rates whose CI excludes zero but whose magnitude is under this are still
# reported with a direction; the CI, not the magnitude, decides "flat".
_ROUND_KG = 3


def _null_result(window_days: int, reason: str) -> dict:
    return {
        "window_days": window_days,
        "trend_kg": None,
        "last_weigh_in": None,
        "rate_kg_per_week": None,
        "ci_kg_per_week": None,
        "state": "unknown",
        "readable": False,
        "readable_note": reason,
        "coverage_pct": 0.0,
        "entries_used": 0,
    }


def compute_trend_rate(
    entries: list,
    as_of: _date,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    ewma_values: Optional[list] = None,
    min_coverage_pct: float = MIN_COVERAGE_PCT,
    min_entries: int = MIN_ENTRIES,
) -> dict:
    """Fit the EWMA trend over the trailing window and report slope ± CI.

    Parameters
    ----------
    entries:
        Time-ordered (oldest first) list of dicts with ``date`` (``datetime.date``)
        and ``weight_kg``. Entries outside ``[as_of - window_days + 1, as_of]``
        are ignored, so callers may pass a longer history unfiltered.
    as_of:
        Last day of the window (inclusive).
    window_days:
        Length of the trailing window in days.
    ewma_values:
        Optional pre-computed EWMA aligned 1:1 with ``entries`` (the output of
        ``weight_ewma.compute_ewma(entries)``). Supplied by callers that already
        smoothed the full history so the smoothing is not restarted mid-series —
        a fresh EWMA over only the window bootstraps on the window's first raw
        value and inherits its noise. Computed here when omitted.

    Returns
    -------
    dict with keys: window_days, trend_kg, last_weigh_in, rate_kg_per_week,
    ci_kg_per_week, state ('losing' | 'gaining' | 'flat' | 'unknown'),
    readable (bool), readable_note (str|None), coverage_pct, entries_used.

    ``trend_kg`` is the EWMA value on the most recent entry — the "trend weight"
    every other consumer should use in place of the last raw weigh-in.
    """
    if window_days <= 0:
        raise ValueError(f"window_days must be positive, got {window_days}")

    if not entries:
        return _null_result(window_days, "no weigh-ins")

    if ewma_values is None:
        from backend.services.weight_ewma import compute_ewma

        ewma_values = compute_ewma(entries)

    if len(ewma_values) != len(entries):
        raise ValueError(
            f"ewma_values length {len(ewma_values)} does not match entries "
            f"length {len(entries)}"
        )

    window_start = as_of - _timedelta(days=window_days - 1)
    points: list[tuple[int, float]] = []
    for entry, smoothed in zip(entries, ewma_values):
        d = entry["date"]
        if d < window_start or d > as_of:
            continue
        points.append(((d - window_start).days, float(smoothed)))

    if not points:
        return _null_result(window_days, "no weigh-ins inside the window")

    # One point per day — a double weigh-in on one day must not double its weight
    # in the fit. Last value for the day wins (matches the EWMA's own ordering).
    by_day: dict[int, float] = {}
    for day_offset, value in points:
        by_day[day_offset] = value
    xs = sorted(by_day)
    n = len(xs)

    trend_kg = round(by_day[xs[-1]], 2)
    last_weigh_in = (window_start + _timedelta(days=xs[-1])).isoformat()
    coverage_pct = round(100.0 * n / window_days, 1)

    readable = True
    readable_note: Optional[str] = None
    if n < min_entries:
        readable = False
        readable_note = f"only {n} weigh-in days in the window (need {min_entries})"
    elif coverage_pct < min_coverage_pct:
        readable = False
        readable_note = (
            f"weigh-in coverage {coverage_pct}% is below the "
            f"{min_coverage_pct}% the rate needs to be readable"
        )

    if n < 3:
        # No residual degrees of freedom — a rate without a CI would read as
        # certain, which is exactly the failure this module exists to prevent.
        out = _null_result(window_days, readable_note or "fewer than 3 weigh-in days")
        out.update({
            "trend_kg": trend_kg,
            "last_weigh_in": last_weigh_in,
            "coverage_pct": coverage_pct,
            "entries_used": n,
        })
        return out

    mean_x = sum(xs) / n
    mean_y = sum(by_day[x] for x in xs) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (by_day[x] - mean_y) for x in xs)

    if sxx == 0:
        out = _null_result(window_days, "all weigh-ins fall on a single day")
        out.update({
            "trend_kg": trend_kg,
            "last_weigh_in": last_weigh_in,
            "coverage_pct": coverage_pct,
            "entries_used": n,
        })
        return out

    slope_per_day = sxy / sxx
    intercept = mean_y - slope_per_day * mean_x
    sse = sum((by_day[x] - (intercept + slope_per_day * x)) ** 2 for x in xs)
    residual_var = sse / (n - 2)
    se_slope = math.sqrt(residual_var / sxx) if residual_var > 0 else 0.0

    rate_per_week = slope_per_day * 7.0
    ci_per_week = T_CRIT_95 * se_slope * 7.0

    lower = rate_per_week - ci_per_week
    upper = rate_per_week + ci_per_week
    if lower <= 0.0 <= upper:
        state = "flat"
    elif rate_per_week < 0:
        state = "losing"
    else:
        state = "gaining"

    return {
        "window_days": window_days,
        "trend_kg": trend_kg,
        "last_weigh_in": last_weigh_in,
        "rate_kg_per_week": round(rate_per_week, _ROUND_KG),
        "ci_kg_per_week": round(ci_per_week, _ROUND_KG),
        "state": state,
        "readable": readable,
        "readable_note": readable_note,
        "coverage_pct": coverage_pct,
        "entries_used": n,
    }
