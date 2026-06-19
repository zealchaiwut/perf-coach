"""Tests for issue #688: Add strength TSS via session-RPE method

Pure function tests for the calculate_strength_tss implementation.
Each test is anchored to a specific acceptance criterion from the issue body.
"""
import json
import types
import pytest
from backend.services.tss import calc_strength_tss


# --- Helpers ---

def _workout(session_rpe=None, duration_minutes=None):
    return types.SimpleNamespace(
        session_rpe=session_rpe,
        duration_minutes=duration_minutes,
    )


def _set(rpe, reps):
    return types.SimpleNamespace(rpe=rpe, reps=reps)


def _prefs():
    """Return a preferences object (none required for the current formula)."""
    return types.SimpleNamespace()


# --- Acceptance Criteria Tests ---


def test_strength_tss__session_rpe_60min_rpe10():
    """AC: 60 minutes at RPE 10 returns tss = 100."""
    result = calc_strength_tss(session_rpe=10, duration_minutes=60)
    assert result["tss"] == 100, f"Expected TSS=100, got {result['tss']}"
    assert result["method"] == "session_rpe"
    assert result["is_estimate"] is True


def test_strength_tss__session_rpe_60min_rpe7():
    """AC: 60 minutes at RPE 7 returns tss = 49 (rounded to whole number)."""
    result = calc_strength_tss(session_rpe=7, duration_minutes=60)
    assert result["tss"] == 49, f"Expected TSS=49, got {result['tss']}"
    assert result["method"] == "session_rpe"
    assert result["is_estimate"] is True


def test_strength_tss__derived_from_per_set_rpe():
    """AC: Derived session RPE = ((8*10) + (9*8) + (7*12)) / 30 = 7.8667
    SI = 0.78667
    TSS = round((0.78667^2) * 45 / 60 * 100) = 46
    """
    sets = [
        _set(rpe=8, reps=10),
        _set(rpe=9, reps=8),
        _set(rpe=7, reps=12),
    ]
    result = calc_strength_tss(session_rpe=None, duration_minutes=45, sets=sets)
    assert result["tss"] == 46, f"Expected TSS=46, got {result['tss']}"
    assert result["method"] == "session_rpe"
    assert result["is_estimate"] is True
    assert result["debug"]["session_rpe_source"] == "derived"


def test_strength_tss__missing_rpe_returns_null():
    """AC: When no session RPE and no sufficient per-set data, returns tss: null, method: "none"."""
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=[])
    assert result["tss"] is None, f"Expected TSS=None, got {result['tss']}"
    assert result["method"] == "none"
    assert result["is_estimate"] is False
    assert "reason" in result["debug"]


def test_strength_tss__missing_duration_returns_null():
    """AC: When no duration, returns tss: null, method: "none" with reason."""
    sets = [_set(rpe=8, reps=10), _set(rpe=9, reps=8)]
    result = calc_strength_tss(session_rpe=None, duration_minutes=None, sets=sets)
    assert result["tss"] is None, f"Expected TSS=None, got {result['tss']}"
    assert result["method"] == "none"
    assert result["is_estimate"] is False
    assert "reason" in result["debug"]
    assert "duration" in result["debug"]["reason"].lower()


def test_strength_tss__return_shape():
    """AC: Return object always includes tss, method, is_estimate, and debug."""
    result = calc_strength_tss(session_rpe=10, duration_minutes=60)
    assert set(result.keys()) == {"tss", "method", "is_estimate", "debug"}


def test_strength_tss__direct_rpe_source():
    """AC: When session RPE is provided directly, debug shows source: "direct"."""
    result = calc_strength_tss(session_rpe=8, duration_minutes=45)
    assert result["debug"]["session_rpe_source"] == "direct"
    assert result["debug"]["session_rpe"] == 8


def test_strength_tss__intensity_calculation():
    """AC: session_intensity is computed as session_rpe divided by 10."""
    result = calc_strength_tss(session_rpe=7, duration_minutes=60)
    assert result["debug"]["session_intensity"] == 0.7


def test_strength_tss__formula():
    """AC: tss = session_intensity^2 * (duration_minutes / 60) * 100."""
    # Manual test: RPE=8, duration=60 min
    # SI = 8/10 = 0.8
    # TSS = 0.8^2 * 60/60 * 100 = 0.64 * 1 * 100 = 64
    result = calc_strength_tss(session_rpe=8, duration_minutes=60)
    assert result["tss"] == 64
