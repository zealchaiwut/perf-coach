"""Tests for issue #1093: Fix off-by-one in _compute_session_signals 40-min threshold.

AC1: `_compute_session_signals` uses `dur <= 40 * 60` (i.e., <= 2400).
AC2: duration == 2400 → endurance_signal_note is "— run under 40 min".
AC3: duration == 2400 → compute_endurance_signal returns None.
AC4: duration == 2401 → endurance signal computed normally; note is not "run under 40 min" or "insufficient data".
AC5: duration == 2399 → endurance_signal_note is "— run under 40 min".
"""
from types import SimpleNamespace

import pytest

from backend.main import _compute_session_signals
from backend.services.endurance_signal import compute_endurance_signal


def _make_workout(duration_seconds, endurance_signal=None, speed_signal=None):
    """Create a minimal Workout-like object for _compute_session_signals."""
    return SimpleNamespace(
        duration_seconds=duration_seconds,
        endurance_signal=endurance_signal,
        speed_signal=speed_signal,
    )


# ── AC1: threshold is <= not < ────────────────────────────────────────────────

def test_threshold_is_lte_2400_for_2400s():
    """AC1/AC2: duration exactly 2400 s → note is 'run under 40 min', not 'insufficient data'."""
    w = _make_workout(2400, endurance_signal=None)
    result = _compute_session_signals(w)
    assert result["endurance_signal_note"] == "— run under 40 min", (
        f"Expected '— run under 40 min' for 2400 s, got: {result['endurance_signal_note']!r}"
    )


# ── AC2: exact boundary note ──────────────────────────────────────────────────

def test_note_run_under_40_min_for_2400s():
    """AC2: For duration == 2400 s, endurance_signal_note is '— run under 40 min'."""
    w = _make_workout(2400, endurance_signal=None)
    result = _compute_session_signals(w)
    assert result["endurance_signal_note"] == "— run under 40 min"


# ── AC3: compute_endurance_signal still returns None for 2400 s ───────────────

def test_endurance_signal_none_for_2400s():
    """AC3: compute_endurance_signal returns None (null result) for duration == 2400 s."""
    workout = {"duration_seconds": 2400}
    result = compute_endurance_signal(workout, splits=[])
    assert result["endurance_signal"] is None, (
        f"Expected None for duration 2400 s, got: {result['endurance_signal']!r}"
    )


def test_compute_endurance_signal_boundary_unchanged():
    """AC3: eligibility logic in compute_endurance_signal is unchanged — 2400 s is still ineligible."""
    workout = {"duration_seconds": 2400}
    result = compute_endurance_signal(workout, None)
    assert result["endurance_signal"] is None
    assert result["decoupling_percent"] is None
    assert result["endurance_signal_source"] is None


# ── AC4: duration > 2400 produces a real signal (when data is present) ────────

def test_note_absent_when_endurance_signal_present_for_2401s():
    """AC4: duration > 2400 with a valid endurance_signal → note is None (not an error string)."""
    w = _make_workout(2401, endurance_signal=85.0)
    result = _compute_session_signals(w)
    assert result["endurance_signal_note"] is None, (
        f"endurance_signal_note should be None when signal is present, got: {result['endurance_signal_note']!r}"
    )
    assert result["endurance_signal"] == pytest.approx(85.0)


def test_note_not_run_under_40_for_2401s_with_signal():
    """AC4: duration 2401 s with a real signal → note is not 'run under 40 min' or 'insufficient data'."""
    w = _make_workout(2401, endurance_signal=72.3)
    result = _compute_session_signals(w)
    note = result["endurance_signal_note"]
    assert note != "— run under 40 min", f"Should not be 'run under 40 min' for 2401 s: {note!r}"
    assert note != "— insufficient data", f"Should not be 'insufficient data' for 2401 s: {note!r}"


# ── AC5: duration < 2400 still shows "run under 40 min" ──────────────────────

def test_note_run_under_40_min_for_2399s():
    """AC5: duration == 2399 s → note remains '— run under 40 min'."""
    w = _make_workout(2399, endurance_signal=None)
    result = _compute_session_signals(w)
    assert result["endurance_signal_note"] == "— run under 40 min", (
        f"Expected '— run under 40 min' for 2399 s, got: {result['endurance_signal_note']!r}"
    )


def test_note_run_under_40_min_for_zero_duration():
    """AC5 (edge): zero duration → note is '— run under 40 min'."""
    w = _make_workout(0, endurance_signal=None)
    result = _compute_session_signals(w)
    assert result["endurance_signal_note"] == "— run under 40 min"


def test_note_run_under_40_min_for_none_duration():
    """AC5 (edge): None duration treated as 0 → note is '— run under 40 min'."""
    w = _make_workout(None, endurance_signal=None)
    result = _compute_session_signals(w)
    assert result["endurance_signal_note"] == "— run under 40 min"
