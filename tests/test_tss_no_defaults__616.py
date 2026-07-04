"""Tests for issue #616: Remove hardcoded fallback thresholds from get_user_thresholds.

Each test is anchored to a specific acceptance criterion.

Acceptance Criteria covered:
  AC-1: FTP_W=280, THRESHOLD_HR=170, THRESHOLD_PACE_SEC_PER_KM=270 no longer returned
        as fallback values from get_user_thresholds()
  AC-2: get_user_thresholds() returns None for each field when user has no
        user_preferences row or the corresponding column is NULL
  AC-3: estimate_tss_for_workout() returns (None, "none") and skips all TSS
        computation when any threshold required for the workout type is None
  AC-4: A user with all thresholds configured continues to have TSS computed
        correctly using their actual values
  AC-5: No TSS value is produced for a workout belonging to a user with missing
        thresholds — the return value is (None, "none") so callers write NULL
"""
import types
import unittest.mock as mock

import pytest

from backend.services.tss import get_user_thresholds, estimate_tss_for_workout


# ── helpers ───────────────────────────────────────────────────────────────────

def _db_returning(row):
    """Return a mock db whose execute().fetchone() returns row."""
    db = mock.MagicMock()
    db.execute.return_value.fetchone.return_value = row
    return db


def _prefs_row(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None):
    return types.SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace_seconds_per_km,
    )


def _workout(avg_power_w=None, avg_hr=None, distance_km=None,
             duration_seconds=3600, avg_pace_seconds_per_km=None):
    return types.SimpleNamespace(
        avg_power_w=avg_power_w,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        avg_pace_seconds_per_km=avg_pace_seconds_per_km,
    )


# ── AC-2: get_user_thresholds returns None when no prefs row ──────────────────

def test_get_user_thresholds_no_row_returns_none_triple():
    """AC-2: No user_preferences row → all three threshold fields are None."""
    db = _db_returning(None)
    result = get_user_thresholds("user-abc", db)
    assert result == (None, None, None)


def test_get_user_thresholds_db_none_returns_none_triple():
    """AC-2: db=None → all three threshold fields are None."""
    result = get_user_thresholds("user-abc", None)
    assert result == (None, None, None)


def test_get_user_thresholds_user_id_none_returns_none_triple():
    """AC-2: user_id=None → all three threshold fields are None."""
    result = get_user_thresholds(None, mock.MagicMock())
    assert result == (None, None, None)


def test_get_user_thresholds_null_ftp_returns_none_for_ftp():
    """AC-2: ftp_w is NULL in the DB row → ftp_w is None, others returned as-is."""
    row = _prefs_row(ftp_w=None, threshold_hr=170, threshold_pace_seconds_per_km=270)
    ftp, hr, pace = get_user_thresholds("user-1", _db_returning(row))
    assert ftp is None
    assert hr == 170
    assert pace == 270


def test_get_user_thresholds_null_hr_returns_none_for_hr():
    """AC-2: threshold_hr is NULL in the DB row → threshold_hr is None, others returned as-is."""
    row = _prefs_row(ftp_w=280, threshold_hr=None, threshold_pace_seconds_per_km=270)
    ftp, hr, pace = get_user_thresholds("user-1", _db_returning(row))
    assert ftp == 280
    assert hr is None
    assert pace == 270


def test_get_user_thresholds_null_pace_returns_none_for_pace():
    """AC-2: threshold_pace is NULL in the DB row → threshold_pace is None, others returned as-is."""
    row = _prefs_row(ftp_w=280, threshold_hr=170, threshold_pace_seconds_per_km=None)
    ftp, hr, pace = get_user_thresholds("user-1", _db_returning(row))
    assert ftp == 280
    assert hr == 170
    assert pace is None


def test_get_user_thresholds_all_null_fields_returns_none_triple():
    """AC-2: Row exists but all three fields are NULL → (None, None, None)."""
    row = _prefs_row(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None)
    result = get_user_thresholds("user-1", _db_returning(row))
    assert result == (None, None, None)


# ── AC-1: Hardcoded constants not returned as fallbacks ───────────────────────

def test_missing_row_does_not_return_280_170_270():
    """AC-1: When no prefs row exists, returned values are NOT the old hardcoded defaults."""
    db = _db_returning(None)
    ftp, hr, pace = get_user_thresholds("user-1", db)
    assert ftp != 280, "ftp_w must not silently fall back to hardcoded 280"
    assert hr != 170, "threshold_hr must not silently fall back to hardcoded 170"
    assert pace != 270, "threshold_pace must not silently fall back to hardcoded 270"


# ── AC-4: Real values returned when thresholds are configured ─────────────────

def test_get_user_thresholds_all_set_returns_configured_values():
    """AC-4: All fields populated in DB → exact configured values returned."""
    row = _prefs_row(ftp_w=255, threshold_hr=163, threshold_pace_seconds_per_km=312)
    ftp, hr, pace = get_user_thresholds("user-1", _db_returning(row))
    assert ftp == 255
    assert hr == 163
    assert pace == 312


# ── AC-3: estimate_tss_for_workout skips when required threshold is None ──────

def test_estimate_tss_power_data_but_no_ftp_returns_none():
    """AC-3: Power data present but ftp_w=None → (None, 'none')."""
    w = _workout(avg_power_w=300, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, None, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss is None
    assert method == "none"


def test_estimate_tss_pace_data_but_no_pace_threshold_returns_none():
    """AC-3: Pace data present but threshold_pace=None → (None, 'none')."""
    w = _workout(avg_pace_seconds_per_km=300, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, None, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss is None
    assert method == "none"


def test_estimate_tss_hr_data_but_no_hr_threshold_returns_none():
    """AC-3: HR data present but threshold_hr=None → (None, 'none')."""
    w = _workout(avg_hr=155, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, None, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss is None
    assert method == "none"


def test_estimate_tss_power_and_hr_data_no_ftp_falls_to_hr():
    """AC-3: Power data (no ftp_w) + HR data (threshold_hr set) → falls through to HR method."""
    w = _workout(avg_power_w=300, avg_hr=160, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, 170, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss is not None
    assert method == "hr"


def test_estimate_tss_partially_configured_run_returns_none():
    """AC-3/UAT-5: Only ftp_w set; run workout (pace data, no power) → (None, 'none')."""
    w = _workout(avg_pace_seconds_per_km=300, duration_seconds=3600)
    # ftp_w=280 but threshold_pace=None, threshold_hr=None
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(280, None, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss is None
    assert method == "none"


def test_estimate_tss_distance_converts_to_pace_no_threshold_returns_none():
    """AC-3: Workout with distance/duration (→ derived pace) but no threshold_pace → (None, 'none')."""
    # No explicit avg_pace but has distance + duration → pace derived internally
    w = _workout(distance_km=12.0, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, None, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss is None
    assert method == "none"


# ── AC-4: Correct TSS when all thresholds are configured ─────────────────────

def test_estimate_tss_power_computes_correctly_with_ftp():
    """AC-4: ftp_w=280, avg_power=280, 60 min → TSS=100."""
    w = _workout(avg_power_w=280, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(280, 170, 270)):
        tss, method = estimate_tss_for_workout(w)
    assert tss == 100
    assert method == "power"


def test_estimate_tss_hr_computes_correctly_with_threshold():
    """AC-4: threshold_hr=170, avg_hr=170, 60 min → TSS=100."""
    w = _workout(avg_hr=170, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, 170, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss == 100
    assert method == "hr"


def test_estimate_tss_pace_computes_correctly_with_threshold():
    """AC-4: threshold_pace=300, avg_pace=300 (12km in 3600s), 60 min → TSS=100."""
    w = _workout(avg_pace_seconds_per_km=300, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, None, 300)):
        tss, method = estimate_tss_for_workout(w)
    assert tss == 100
    assert method == "pace"


# ── AC-5: No TSS produced for user with missing thresholds ────────────────────

def test_estimate_tss_with_all_intensity_data_no_thresholds_returns_none():
    """AC-5: Workout has power+HR data but no thresholds → (None, 'none'), no TSS written."""
    w = _workout(avg_power_w=300, avg_hr=155, duration_seconds=3600)
    with mock.patch("backend.services.tss.get_user_thresholds", return_value=(None, None, None)):
        tss, method = estimate_tss_for_workout(w)
    assert tss is None, "TSS must be None so callers write NULL to the workouts table"
    assert method == "none"
