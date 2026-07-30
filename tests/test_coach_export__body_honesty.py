"""Body honesty — weight_trend_rate must refuse to overstate what it knows.

Two properties matter, both from spec §7:

- when the confidence interval includes zero, ``state`` is ``flat`` — a rate the
  data cannot distinguish from no change must not be reported as a direction;
- when coverage is below the threshold, ``readable`` is False — a slope through
  three weigh-ins in 45 days is arithmetic, not evidence.

The rest of the module's contract (window filtering, one-point-per-day, the
degenerate shapes) is covered here too, because every one of them is a path that
would otherwise silently produce a confident-looking number.
"""
from __future__ import annotations

import datetime

import pytest

from backend.services.weight_trend_rate import (
    MIN_COVERAGE_PCT,
    MIN_ENTRIES,
    compute_trend_rate,
)

AS_OF = datetime.date(2026, 7, 30)
WINDOW = 45


def _entries(values: list, *, step_days: int = 1, end: datetime.date = AS_OF) -> list:
    """Build entries ending on ``end``, spaced ``step_days`` apart, oldest first."""
    n = len(values)
    return [
        {
            "date": end - datetime.timedelta(days=(n - 1 - i) * step_days),
            "weight_kg": v,
        }
        for i, v in enumerate(values)
    ]


def _linear(start: float, per_day: float, days: int) -> list:
    return [start + per_day * i for i in range(days)]


def _fit(values: list, *, step_days: int = 1, window_days: int = WINDOW) -> dict:
    """Fit ``values`` AS the trend — i.e. treat them as already smoothed.

    The regression's own behaviour is what most of these tests are about, so the
    EWMA is passed through rather than recomputed; otherwise the smoothing lag
    shifts the slope and the assertions stop being about the fit. The default
    (smooth-it-here) path has its own tests at the bottom.
    """
    entries = _entries(values, step_days=step_days)
    return compute_trend_rate(
        entries, AS_OF, window_days=window_days, ewma_values=list(values)
    )


# ── CI includes zero → flat ──────────────────────────────────────────────────

def test_ci_including_zero_yields_flat():
    """Noise around a constant weight has a slope, but not a direction."""
    noisy = [78.0, 78.4, 77.7, 78.2, 77.8, 78.3, 77.6, 78.1, 77.9, 78.2,
             77.7, 78.4, 77.8, 78.0, 78.3, 77.6, 78.2, 77.9, 78.1, 77.8]
    result = _fit(noisy)

    lower = result["rate_kg_per_week"] - result["ci_kg_per_week"]
    upper = result["rate_kg_per_week"] + result["ci_kg_per_week"]
    assert lower <= 0.0 <= upper
    assert result["state"] == "flat"


def test_clear_loss_is_reported_as_losing_with_a_ci_excluding_zero():
    result = _fit(_linear(80.0, -0.03, 30))
    assert result["state"] == "losing"
    assert result["rate_kg_per_week"] < 0
    assert result["rate_kg_per_week"] + result["ci_kg_per_week"] < 0


def test_clear_gain_is_reported_as_gaining():
    result = _fit(_linear(70.0, 0.025, 30))
    assert result["state"] == "gaining"
    assert result["rate_kg_per_week"] > 0


def test_a_perfect_line_has_a_zero_width_ci_and_the_exact_weekly_slope():
    result = _fit(_linear(80.0, -0.02, 30))
    assert result["ci_kg_per_week"] == pytest.approx(0.0, abs=1e-6)
    assert result["rate_kg_per_week"] == pytest.approx(-0.14, abs=1e-3)


def test_identical_central_rate_is_flat_or_losing_depending_on_scatter():
    """The CI, not the magnitude, decides the direction — that is the point.

    The scatter pattern has period 4 over 28 points, so it is uncorrelated with
    the day index: both series fit the SAME slope and differ only in residual
    spread. Same number, opposite verdict.
    """
    line = _linear(80.0, -0.02, 28)
    balanced = (0.9, -0.9, -0.9, 0.9)
    tight = _fit(line)
    scattered = _fit([v + balanced[i % 4] for i, v in enumerate(line)])

    assert scattered["rate_kg_per_week"] == pytest.approx(
        tight["rate_kg_per_week"], abs=1e-6
    )
    assert tight["state"] == "losing"
    assert scattered["ci_kg_per_week"] > tight["ci_kg_per_week"]
    assert scattered["state"] == "flat"


# ── Coverage → readable ──────────────────────────────────────────────────────

def test_low_coverage_makes_the_rate_unreadable():
    """Nine weigh-ins in 45 days is 20% coverage — under the threshold."""
    result = _fit(_linear(80.0, -0.15, 9), step_days=5)

    assert result["coverage_pct"] < MIN_COVERAGE_PCT
    assert result["readable"] is False
    assert "coverage" in result["readable_note"]
    # The rate is still computed — the flag is what stops it being presented.
    assert result["rate_kg_per_week"] is not None


def test_dense_coverage_is_readable():
    result = _fit(_linear(80.0, -0.02, 30))
    assert result["coverage_pct"] >= MIN_COVERAGE_PCT
    assert result["readable"] is True
    assert result["readable_note"] is None


def test_too_few_entries_is_unreadable_even_at_high_coverage():
    """Four consecutive days in a 5-day window is 80% coverage but 4 points."""
    result = _fit(_linear(80.0, -0.05, 4), window_days=5)
    assert result["entries_used"] < MIN_ENTRIES
    assert result["readable"] is False
    assert "weigh-in days" in result["readable_note"]


# ── Degenerate shapes never produce a confident number ───────────────────────

def test_no_entries_returns_the_null_shape():
    result = compute_trend_rate([], AS_OF)
    assert result["state"] == "unknown"
    assert result["readable"] is False
    assert result["rate_kg_per_week"] is None
    assert result["trend_kg"] is None


def test_entries_all_outside_the_window_are_ignored():
    old = _entries(_linear(80.0, -0.02, 20), end=AS_OF - datetime.timedelta(days=200))
    result = compute_trend_rate(old, AS_OF, window_days=WINDOW)
    assert result["state"] == "unknown"
    assert result["rate_kg_per_week"] is None


def test_two_points_report_a_trend_but_no_rate():
    """n - 2 == 0: no residual variance, so no CI, so no rate at all."""
    result = _fit([80.0, 79.0])
    assert result["trend_kg"] is not None
    assert result["rate_kg_per_week"] is None
    assert result["ci_kg_per_week"] is None
    assert result["readable"] is False


def test_all_entries_on_one_day_report_no_rate():
    same_day = [
        {"date": AS_OF, "weight_kg": 80.0},
        {"date": AS_OF, "weight_kg": 80.4},
        {"date": AS_OF, "weight_kg": 79.8},
    ]
    result = compute_trend_rate(same_day, AS_OF, window_days=WINDOW)
    assert result["rate_kg_per_week"] is None
    assert result["entries_used"] == 1


def test_two_weigh_ins_on_one_day_count_once():
    """A double weigh-in must not get double weight in the fit."""
    values = _linear(80.0, -0.02, 20)
    entries = _entries(values)
    duplicated = entries + [{"date": entries[-1]["date"], "weight_kg": 76.0}]
    dup_values = values + [76.0]

    base = _fit(values)
    dup = compute_trend_rate(
        duplicated, AS_OF, window_days=WINDOW, ewma_values=dup_values
    )
    assert dup["entries_used"] == base["entries_used"]


# ── trend_kg is the smoothed value, not the last raw weigh-in ────────────────

def test_trend_kg_is_the_ewma_not_the_raw_weight():
    """A single heavy day must not become the reported body mass."""
    entries = _entries([78.0] * 20 + [82.0])
    result = compute_trend_rate(entries, AS_OF, window_days=WINDOW)
    assert result["trend_kg"] < 82.0
    assert result["last_weigh_in"] == AS_OF.isoformat()


def test_supplied_ewma_is_used_verbatim():
    """Callers smooth the FULL history so the EWMA isn't re-bootstrapped inside
    the window; the module must honour what it is handed."""
    entries = _entries(_linear(80.0, -0.02, 20))
    flat_ewma = [77.0] * len(entries)
    result = compute_trend_rate(
        entries, AS_OF, window_days=WINDOW, ewma_values=flat_ewma
    )
    assert result["trend_kg"] == 77.0
    assert result["state"] == "flat"


def test_mismatched_ewma_length_is_rejected():
    entries = _entries([80.0, 79.5, 79.0])
    with pytest.raises(ValueError, match="does not match entries"):
        compute_trend_rate(entries, AS_OF, ewma_values=[80.0])


def test_non_positive_window_is_rejected():
    with pytest.raises(ValueError, match="window_days must be positive"):
        compute_trend_rate(_entries([80.0, 79.0]), AS_OF, window_days=0)
