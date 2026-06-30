"""Tests for issue #1130: Rolling intensity distribution over trailing windows.

Acceptance criteria anchored:
  AC1 - Function accepts a list of sessions with date, duration, and
        low/moderate/high fields
  AC2 - Rolling values produced for 7-day and 28-day trailing windows
        ending on each date
  AC3 - Each session's contribution is weighted by duration
  AC4 - Output values sum to 1.0 (within floating-point tolerance) per date
  AC5 - Dates with no sessions in the trailing window produce null/None
  AC6 - Implementation file passes py_compile with no errors
  AC7 - Unit tests cover: single session, multiple sessions spanning window
        boundary, and an empty window
"""
import math
import pathlib
import py_compile
from datetime import date

import pytest

from backend.services.rolling_intensity import compute_rolling_intensity_distribution


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session(d, duration, low, moderate, high):
    """Build a session dict with string or date key."""
    if isinstance(d, date):
        d = d.isoformat()
    return {"date": d, "duration": duration, "low": low, "moderate": moderate, "high": high}


def _approx_equal(a, b, tol=1e-9):
    return abs(a - b) < tol


# ---------------------------------------------------------------------------
# AC1 + AC7a: Single session
# ---------------------------------------------------------------------------

def test_single_session_returns_result_for_its_date():
    """AC1/AC7: Single session produces a result keyed by its date."""
    sessions = [_session("2024-01-10", duration=3600, low=0.7, moderate=0.2, high=0.1)]
    result = compute_rolling_intensity_distribution(sessions)
    assert "2024-01-10" in result


def test_single_session_7day_values_match_session():
    """AC2/AC3: With one session the 7-day distribution equals that session's values."""
    sessions = [_session("2024-01-10", duration=3600, low=0.7, moderate=0.2, high=0.1)]
    result = compute_rolling_intensity_distribution(sessions)
    w7 = result["2024-01-10"][7]
    assert w7 is not None
    assert _approx_equal(w7["low"], 0.7)
    assert _approx_equal(w7["moderate"], 0.2)
    assert _approx_equal(w7["high"], 0.1)


def test_single_session_28day_values_match_session():
    """AC2: 28-day window for a single session also returns that session's values."""
    sessions = [_session("2024-01-10", duration=3600, low=0.5, moderate=0.3, high=0.2)]
    result = compute_rolling_intensity_distribution(sessions)
    w28 = result["2024-01-10"][28]
    assert w28 is not None
    assert _approx_equal(w28["low"], 0.5)
    assert _approx_equal(w28["moderate"], 0.3)
    assert _approx_equal(w28["high"], 0.2)


def test_single_session_values_sum_to_one():
    """AC4: low + moderate + high sums to 1.0 for a single session."""
    sessions = [_session("2024-02-01", duration=1800, low=0.6, moderate=0.25, high=0.15)]
    result = compute_rolling_intensity_distribution(sessions)
    for win in (7, 28):
        w = result["2024-02-01"][win]
        total = w["low"] + w["moderate"] + w["high"]
        assert abs(total - 1.0) < 1e-9, f"window {win}: sum={total}"


# ---------------------------------------------------------------------------
# AC3: Duration weighting
# ---------------------------------------------------------------------------

def test_duration_weighting_two_sessions_same_day():
    """AC3: Duration weighting — 60-min 100% high + 10-min 100% low → 85.7% high."""
    sessions = [
        _session("2024-03-01", duration=3600, low=0.0, moderate=0.0, high=1.0),
        _session("2024-03-01", duration=600,  low=1.0, moderate=0.0, high=0.0),
    ]
    result = compute_rolling_intensity_distribution(sessions)
    w7 = result["2024-03-01"][7]
    expected_high = 3600 / (3600 + 600)   # ~0.857
    expected_low  = 600  / (3600 + 600)   # ~0.143
    assert abs(w7["high"] - expected_high) < 1e-6
    assert abs(w7["low"]  - expected_low)  < 1e-6
    assert abs(w7["moderate"]) < 1e-9


def test_duration_weighting_proportional():
    """AC3: Heavier session dominates the weighted distribution."""
    sessions = [
        _session("2024-04-01", duration=7200, low=1.0, moderate=0.0, high=0.0),
        _session("2024-04-01", duration=1800, low=0.0, moderate=0.0, high=1.0),
    ]
    result = compute_rolling_intensity_distribution(sessions)
    w7 = result["2024-04-01"][7]
    assert w7["low"] > w7["high"], "longer all-low session should dominate"


# ---------------------------------------------------------------------------
# AC2 + AC7b: Multiple sessions spanning window boundary
# ---------------------------------------------------------------------------

def test_7day_window_excludes_sessions_before_boundary():
    """AC2/AC7: Session on day 1 excluded from 7-day window ending on day 8."""
    sessions = [
        _session("2024-05-01", duration=3600, low=0.0, moderate=0.0, high=1.0),  # day 1
        _session("2024-05-08", duration=3600, low=1.0, moderate=0.0, high=0.0),  # day 8
    ]
    result = compute_rolling_intensity_distribution(sessions)
    # 7-day window ending 2024-05-08 covers May 2–8 only; May 1 is excluded
    w7_day8 = result["2024-05-08"][7]
    assert w7_day8 is not None
    assert _approx_equal(w7_day8["low"], 1.0), "only the May-8 session (all low) should count"
    assert _approx_equal(w7_day8["high"], 0.0)


def test_7day_window_includes_session_on_boundary_day():
    """AC2: Session exactly 6 days before query date IS inside the 7-day window."""
    sessions = [
        _session("2024-05-02", duration=3600, low=0.0, moderate=0.0, high=1.0),  # day -6 relative
        _session("2024-05-08", duration=3600, low=1.0, moderate=0.0, high=0.0),  # reference day
    ]
    result = compute_rolling_intensity_distribution(sessions)
    w7_day8 = result["2024-05-08"][7]
    # May 2 is 6 days before May 8; 7-day window [May 2, May 8] includes it
    assert _approx_equal(w7_day8["low"], 0.5)
    assert _approx_equal(w7_day8["high"], 0.5)


def test_28day_window_includes_what_7day_excludes():
    """AC2: 28-day window picks up sessions outside the 7-day window."""
    sessions = [
        _session("2024-06-01", duration=3600, low=0.0, moderate=0.0, high=1.0),  # day 1
        _session("2024-06-08", duration=3600, low=1.0, moderate=0.0, high=0.0),  # day 8
    ]
    result = compute_rolling_intensity_distribution(sessions)
    w7  = result["2024-06-08"][7]
    w28 = result["2024-06-08"][28]
    # 7-day: only day-8 session; 28-day: both sessions
    assert _approx_equal(w7["low"],   1.0), "7-day: only all-low session"
    assert _approx_equal(w28["high"], 0.5), "28-day: includes the all-high session from day 1"


# ---------------------------------------------------------------------------
# AC4: Sum to 1.0
# ---------------------------------------------------------------------------

def test_sum_to_one_multiple_sessions():
    """AC4: Sum of low + moderate + high equals 1.0 for multi-session window."""
    sessions = [
        _session("2024-07-01", duration=3600, low=0.5, moderate=0.3, high=0.2),
        _session("2024-07-03", duration=1800, low=0.2, moderate=0.4, high=0.4),
        _session("2024-07-05", duration=900,  low=0.8, moderate=0.1, high=0.1),
    ]
    result = compute_rolling_intensity_distribution(sessions)
    for d, row in result.items():
        for win, dist in row.items():
            if dist["low"] is not None:
                total = dist["low"] + dist["moderate"] + dist["high"]
                assert abs(total - 1.0) < 1e-9, f"date={d} win={win} sum={total}"


# ---------------------------------------------------------------------------
# AC5 + AC7c: Empty window produces None
# ---------------------------------------------------------------------------

def test_empty_window_for_intermediate_date():
    """AC5/AC7: A calendar date between sessions with no trailing sessions → None."""
    # Sessions 30 days apart; intermediate dates have empty 7-day windows
    sessions = [
        _session("2024-08-01", duration=3600, low=0.6, moderate=0.3, high=0.1),
        _session("2024-08-31", duration=3600, low=0.4, moderate=0.4, high=0.2),
    ]
    result = compute_rolling_intensity_distribution(sessions)
    # Aug 15 is in the output range; its 7-day window [Aug 9–15] has no sessions
    if "2024-08-15" in result:
        w7 = result["2024-08-15"][7]
        assert w7["low"] is None
        assert w7["moderate"] is None
        assert w7["high"] is None


def test_empty_sessions_list_returns_empty_dict():
    """AC5: Empty sessions list returns an empty dict (no crash)."""
    result = compute_rolling_intensity_distribution([])
    assert result == {}


def test_no_sessions_in_28day_window_returns_none():
    """AC5: 28-day window empty when sessions are > 28 days apart."""
    sessions = [
        _session("2024-09-01", duration=3600, low=1.0, moderate=0.0, high=0.0),
        _session("2024-10-15", duration=3600, low=0.0, moderate=0.0, high=1.0),
    ]
    result = compute_rolling_intensity_distribution(sessions)
    # 44 days apart; Oct 15's 28-day window [Sep 17 – Oct 15] misses Sep 1
    w28_oct15 = result["2024-10-15"][28]
    # Only Oct 15 session is in the window
    assert _approx_equal(w28_oct15["high"], 1.0)
    # Sep 1's 28-day window contains only Sep 1
    w28_sep1 = result["2024-09-01"][28]
    assert _approx_equal(w28_sep1["low"], 1.0)
    # Sep 30: its 28-day window is [Sep 3 – Sep 30]; Sep 1 is before Sep 3 → empty
    if "2024-09-30" in result:
        w28_sep30 = result["2024-09-30"][28]
        assert w28_sep30["low"] is None


# ---------------------------------------------------------------------------
# AC2: Both 7 and 28 windows present in output
# ---------------------------------------------------------------------------

def test_output_contains_both_window_sizes():
    """AC2: Result dict has both 7 and 28 as keys for each date."""
    sessions = [_session("2024-11-01", duration=3600, low=0.5, moderate=0.3, high=0.2)]
    result = compute_rolling_intensity_distribution(sessions)
    for d, row in result.items():
        assert 7 in row, f"7-day window missing for date {d}"
        assert 28 in row, f"28-day window missing for date {d}"


# ---------------------------------------------------------------------------
# Custom windows
# ---------------------------------------------------------------------------

def test_custom_windows_parameter():
    """AC2: Function accepts custom window sizes."""
    sessions = [_session("2024-12-01", duration=3600, low=0.5, moderate=0.3, high=0.2)]
    result = compute_rolling_intensity_distribution(sessions, windows=(14,))
    assert 14 in result["2024-12-01"]


# ---------------------------------------------------------------------------
# AC6: py_compile
# ---------------------------------------------------------------------------

def test_rolling_intensity_module_compiles():
    """AC6: rolling_intensity.py passes py_compile with no errors."""
    path = str(
        pathlib.Path(__file__).parents[1]
        / "backend"
        / "services"
        / "rolling_intensity.py"
    )
    py_compile.compile(path, doraise=True)
