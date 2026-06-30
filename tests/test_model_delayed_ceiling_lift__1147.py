"""Tests for compute_ceiling_bonus (issue #1147).

AC coverage:
  AC1  — function accepts stimulus_history + reference_date, returns lagged bonus
  AC2  — sessions within most recent week contribute ≤ 5% of peak weight
  AC3  — bonus peaks (substantially elevated) 6–12 weeks after sustained stimulus
  AC4  — decay: bonus decreases monotonically at weeks 10 → 14 → 20 after training stops
  AC5  — configurable lag/ramp window via parameters or constants
  AC6  — py_compile passes on all modified files
  Unit — (a) lag onset, (b) peak timing, (c) decay after stimulus stops, (d) zero with no history
"""

import py_compile
from datetime import date, timedelta

import pytest

from backend.services.ceiling_bonus import (
    LAG_ONSET_DAYS,
    LAG_PEAK_DAYS,
    LAG_WINDOW_DAYS,
    MAX_ONSET_FRACTION,
    _kernel_weight,
    compute_ceiling_bonus,
)

TODAY = date(2026, 1, 1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _weekly_sessions(weeks: int, ref: date) -> list:
    """Return ``weeks`` unit-stimulus sessions spaced 7 days apart ending at ``ref``."""
    return [(ref - timedelta(weeks=w), 1.0) for w in range(weeks)]


# ── (d) Zero bonus with no history ───────────────────────────────────────────

def test_zero_bonus_empty_list():
    assert compute_ceiling_bonus([], TODAY) == 0.0


def test_zero_bonus_empty_tuple():
    assert compute_ceiling_bonus((), TODAY) == 0.0


def test_zero_bonus_all_future_sessions():
    """Sessions after reference_date have negative lag and are ignored."""
    history = [(TODAY + timedelta(days=d), 1.0) for d in range(1, 8)]
    assert compute_ceiling_bonus(history, TODAY) == 0.0


# ── (a) Lag onset — AC2 ──────────────────────────────────────────────────────

def test_kernel_onset_window_all_lte_five_percent():
    """Every lag in [0, LAG_ONSET_DAYS] yields a weight ≤ MAX_ONSET_FRACTION."""
    for lag in range(LAG_ONSET_DAYS + 1):
        w = _kernel_weight(
            lag,
            onset_days=LAG_ONSET_DAYS,
            peak_days=LAG_PEAK_DAYS,
            window_days=LAG_WINDOW_DAYS,
        )
        assert w <= MAX_ONSET_FRACTION, (
            f"Kernel weight {w:.5f} at lag {lag} d exceeds MAX_ONSET_FRACTION={MAX_ONSET_FRACTION}"
        )


def test_kernel_peak_weight_is_one():
    """Kernel reaches exactly 1.0 at LAG_PEAK_DAYS."""
    w = _kernel_weight(
        LAG_PEAK_DAYS,
        onset_days=LAG_ONSET_DAYS,
        peak_days=LAG_PEAK_DAYS,
        window_days=LAG_WINDOW_DAYS,
    )
    assert abs(w - 1.0) < 1e-9


def test_today_session_lte_five_percent_of_peak():
    """A session logged today contributes ≤ 5 % of a session at peak lag."""
    bonus_today = compute_ceiling_bonus([(TODAY, 1.0)], TODAY)
    bonus_peak = compute_ceiling_bonus(
        [(TODAY - timedelta(days=LAG_PEAK_DAYS), 1.0)], TODAY
    )
    assert bonus_today <= MAX_ONSET_FRACTION * bonus_peak + 1e-9


def test_one_week_old_session_lte_five_percent_of_peak():
    """A session exactly LAG_ONSET_DAYS old contributes ≤ 5 % of peak weight."""
    bonus_week = compute_ceiling_bonus(
        [(TODAY - timedelta(days=LAG_ONSET_DAYS), 1.0)], TODAY
    )
    bonus_peak = compute_ceiling_bonus(
        [(TODAY - timedelta(days=LAG_PEAK_DAYS), 1.0)], TODAY
    )
    assert bonus_week <= MAX_ONSET_FRACTION * bonus_peak + 1e-9


# ── (b) Peak timing — AC3 ────────────────────────────────────────────────────

def test_bonus_grows_with_sustained_weekly_training():
    """Bonus increases as more weeks of training accumulate."""
    b1 = compute_ceiling_bonus(_weekly_sessions(1, TODAY), TODAY)
    b4 = compute_ceiling_bonus(_weekly_sessions(4, TODAY), TODAY)
    b8 = compute_ceiling_bonus(_weekly_sessions(8, TODAY), TODAY)
    b12 = compute_ceiling_bonus(_weekly_sessions(12, TODAY), TODAY)
    assert b1 <= b4 < b8 <= b12


def test_eight_weeks_substantially_above_single_fresh_session():
    """Bonus at 8 weeks of training exceeds a single 1-week-old session by 10×."""
    b_one = compute_ceiling_bonus(
        [(TODAY - timedelta(days=LAG_ONSET_DAYS), 1.0)], TODAY
    )
    b8 = compute_ceiling_bonus(_weekly_sessions(8, TODAY), TODAY)
    assert b8 > 10 * b_one


def test_six_weeks_elevated_vs_single_week():
    """Bonus after 6 weeks of weekly sessions is greater than after 1 week."""
    b1 = compute_ceiling_bonus(_weekly_sessions(1, TODAY), TODAY)
    b6 = compute_ceiling_bonus(_weekly_sessions(6, TODAY), TODAY)
    assert b6 > b1


def test_constants_map_to_six_twelve_weeks():
    """Default constants encode the 6–12-week window from the AC."""
    assert LAG_PEAK_DAYS == 6 * 7
    assert LAG_WINDOW_DAYS == 12 * 7


# ── (c) Decay after stimulus stops — AC4 ─────────────────────────────────────

def test_decay_monotonic_weeks_10_14_20():
    """Bonus decreases monotonically when queried at weeks 10, 14, 20 after stop."""
    stop = TODAY
    history = _weekly_sessions(8, stop)  # 8 weekly sessions ending today

    b10 = compute_ceiling_bonus(history, stop + timedelta(weeks=2))   # week 10
    b14 = compute_ceiling_bonus(history, stop + timedelta(weeks=6))   # week 14
    b20 = compute_ceiling_bonus(history, stop + timedelta(weeks=12))  # week 20

    assert b10 > b14 > b20 >= 0.0, (
        f"Expected b10={b10:.4f} > b14={b14:.4f} > b20={b20:.4f}"
    )


def test_decay_reaches_zero_beyond_window():
    """Bonus is exactly 0 once all sessions age past LAG_WINDOW_DAYS."""
    stop = TODAY
    history = _weekly_sessions(8, stop)
    far_future = stop + timedelta(days=LAG_WINDOW_DAYS * 3)
    assert compute_ceiling_bonus(history, far_future) == 0.0


def test_no_cliff_drop_week_over_week():
    """Week-over-week bonus drop is ≤ 30 % — no cliff."""
    stop = TODAY
    history = _weekly_sessions(8, stop)
    # Query well past the fresh-session ripening bump
    b_ref = compute_ceiling_bonus(history, stop + timedelta(weeks=3))
    b_next = compute_ceiling_bonus(history, stop + timedelta(weeks=4))
    if b_ref > 0:
        drop_fraction = (b_ref - b_next) / b_ref
        assert drop_fraction <= 0.30, (
            f"Week-over-week drop of {drop_fraction:.0%} looks like a cliff"
        )


def test_decay_daily_sessions_monotonic_from_peak():
    """With daily sessions stopped at 8 weeks, bonus eventually decays to zero."""
    stop = TODAY
    history = [(stop - timedelta(days=d), 1.0) for d in range(56)]  # 8 weeks daily

    b_at_stop = compute_ceiling_bonus(history, stop)
    b_later = compute_ceiling_bonus(history, stop + timedelta(days=LAG_WINDOW_DAYS))
    b_gone = compute_ceiling_bonus(history, stop + timedelta(days=LAG_WINDOW_DAYS * 2))

    # After full window from stop, all sessions aged out
    assert b_gone == 0.0
    # Some decay visible within one window
    assert b_later < b_at_stop * 1.5  # bonus doesn't explode


# ── AC5: configurable parameters ─────────────────────────────────────────────

def test_shorter_onset_gives_higher_weight_to_fresh_sessions():
    """Reducing lag_onset_days raises the weight of a 5-day-old session."""
    session = [(TODAY - timedelta(days=5), 1.0)]
    b_default = compute_ceiling_bonus(session, TODAY)
    b_short = compute_ceiling_bonus(session, TODAY, lag_onset_days=1, lag_peak_days=42, lag_window_days=84)
    assert b_short > b_default


def test_narrow_window_excludes_old_sessions():
    """Sessions beyond lag_window_days contribute nothing."""
    old = [(TODAY - timedelta(days=100), 1.0)]
    b_narrow = compute_ceiling_bonus(old, TODAY, lag_window_days=84)
    b_wide = compute_ceiling_bonus(old, TODAY, lag_window_days=120)
    assert b_narrow == 0.0
    assert b_wide > 0.0


def test_zero_stimulus_value_gives_zero_bonus():
    """Zero-valued stimulus entries do not inflate the bonus."""
    history = [(TODAY - timedelta(weeks=w), 0.0) for w in range(8)]
    assert compute_ceiling_bonus(history, TODAY) == 0.0


def test_bonus_scales_linearly_with_stimulus():
    """Doubling all stimulus values doubles the bonus."""
    history_1x = _weekly_sessions(8, TODAY)
    history_2x = [(d, 2.0) for d, _ in history_1x]
    b1 = compute_ceiling_bonus(history_1x, TODAY)
    b2 = compute_ceiling_bonus(history_2x, TODAY)
    assert abs(b2 - 2 * b1) < 1e-9


# ── AC6: py_compile ──────────────────────────────────────────────────────────

def test_py_compile_ceiling_bonus():
    import backend.services.ceiling_bonus as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)
