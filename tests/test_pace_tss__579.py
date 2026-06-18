"""Tests for issue #579: Add pure pace-based TSS calculation function.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria covered:
  AC-two-lap      — Two-lap split workout sums per-lap TSS correctly → tss=62
  AC-fallback     — Empty/absent splits fall back to whole-workout avg pace
  AC-threshold    — Missing threshold_pace → tss=null, method="none", reason set
  AC-no-pace      — Missing all pace data → tss=null, method="none", reason set
  AC-intensity    — faster lap (lower s/km) produces intensity > 1
  AC-formula      — lap_tss = (lap_dur/3600) * intensity^2 * 100, summed+rounded
  AC-debug-laps   — debug.laps exposes per-lap detail dict for every lap used
  AC-return-shape — result always has tss, method, debug keys
  AC-none-splits  — splits=None treated same as splits=[]
"""
import types
import pytest

from backend.services.tss import calculate_pace_tss


# ── Helpers ────────────────────────────────────────────────────────────────────

def _split(duration_seconds, distance_km):
    return types.SimpleNamespace(
        duration_seconds=duration_seconds,
        distance_km=distance_km,
    )


# ── AC-two-lap: UAT step 4 two-lap example ────────────────────────────────────

def test_two_lap_workout_returns_expected_tss():
    """AC-two-lap: threshold=330 s/km, lap1=6:00/km (1080s), lap2=5:00/km (1080s) → tss=62.

    Lap 1: dur=1080 s, dist=3 km → pace=360 s/km
      intensity = 330/360 ≈ 0.9167
      lap_tss   = (1080/3600) * 0.9167^2 * 100 ≈ 25.21
    Lap 2: dur=1080 s, dist=3.6 km → pace=300 s/km
      intensity = 330/300 = 1.1
      lap_tss   = (1080/3600) * 1.21 * 100 = 36.3
    total = round(61.51) = 62
    """
    splits = [
        _split(duration_seconds=1080, distance_km=3.0),   # 6:00/km
        _split(duration_seconds=1080, distance_km=3.6),   # 5:00/km
    ]
    result = calculate_pace_tss(
        splits=splits,
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=2160,
        workout_avg_pace_seconds_per_km=None,
    )
    assert result["tss"] == 62
    assert result["method"] == "pace"


def test_two_lap_debug_has_two_entries():
    """AC-debug-laps: two-lap workout exposes two entries in debug.laps."""
    splits = [
        _split(duration_seconds=1080, distance_km=3.0),
        _split(duration_seconds=1080, distance_km=3.6),
    ]
    result = calculate_pace_tss(
        splits=splits,
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=2160,
        workout_avg_pace_seconds_per_km=None,
    )
    assert len(result["debug"]["laps"]) == 2


def test_faster_lap_intensity_exceeds_one():
    """AC-intensity: a lap faster than threshold produces lap_intensity > 1."""
    # pace = 300 s/km, threshold = 330 s/km → 330/300 = 1.1
    splits = [_split(duration_seconds=1080, distance_km=3.6)]
    result = calculate_pace_tss(
        splits=splits,
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=1080,
        workout_avg_pace_seconds_per_km=None,
    )
    lap = result["debug"]["laps"][0]
    assert lap["lap_intensity"] > 1.0


def test_debug_lap_keys_are_present():
    """AC-debug-laps: each lap dict has required keys."""
    splits = [_split(duration_seconds=1080, distance_km=3.0)]
    result = calculate_pace_tss(
        splits=splits,
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=1080,
        workout_avg_pace_seconds_per_km=None,
    )
    lap = result["debug"]["laps"][0]
    assert "lap_duration_seconds" in lap
    assert "lap_pace_seconds_per_km" in lap
    assert "lap_intensity" in lap
    assert "lap_tss" in lap


def test_tss_is_integer():
    """AC-formula: tss is a whole integer (rounded)."""
    splits = [_split(duration_seconds=1080, distance_km=3.0)]
    result = calculate_pace_tss(
        splits=splits,
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=1080,
        workout_avg_pace_seconds_per_km=None,
    )
    assert isinstance(result["tss"], int)


# ── AC-fallback: no splits → whole-workout avg pace ───────────────────────────

def test_empty_splits_falls_back_to_workout_avg_pace():
    """AC-fallback: empty splits list uses workout_avg_pace_seconds_per_km as synthetic lap."""
    # threshold=300, avg_pace=300, 60 min → IF=1, tss=100
    result = calculate_pace_tss(
        splits=[],
        threshold_pace_seconds_per_km=300,
        workout_duration_seconds=3600,
        workout_avg_pace_seconds_per_km=300,
    )
    assert result["tss"] == 100
    assert result["method"] == "pace"


def test_none_splits_falls_back_to_workout_avg_pace():
    """AC-none-splits: splits=None is treated same as empty list."""
    result = calculate_pace_tss(
        splits=None,
        threshold_pace_seconds_per_km=300,
        workout_duration_seconds=3600,
        workout_avg_pace_seconds_per_km=300,
    )
    assert result["tss"] == 100
    assert result["method"] == "pace"


def test_fallback_debug_has_one_lap():
    """AC-debug-laps: fallback to avg pace produces exactly one synthetic lap entry."""
    result = calculate_pace_tss(
        splits=[],
        threshold_pace_seconds_per_km=300,
        workout_duration_seconds=3600,
        workout_avg_pace_seconds_per_km=300,
    )
    assert len(result["debug"]["laps"]) == 1


# ── AC-threshold: missing threshold → null result ─────────────────────────────

def test_missing_threshold_returns_null_tss():
    """AC-threshold: threshold_pace=None → tss=None, method='none'."""
    splits = [_split(duration_seconds=1080, distance_km=3.0)]
    result = calculate_pace_tss(
        splits=splits,
        threshold_pace_seconds_per_km=None,
        workout_duration_seconds=1080,
        workout_avg_pace_seconds_per_km=300,
    )
    assert result["tss"] is None
    assert result["method"] == "none"


def test_missing_threshold_debug_reason():
    """AC-threshold: debug.reason is 'missing threshold_pace_seconds_per_km'."""
    result = calculate_pace_tss(
        splits=[],
        threshold_pace_seconds_per_km=None,
        workout_duration_seconds=3600,
        workout_avg_pace_seconds_per_km=300,
    )
    assert result["debug"]["reason"] == "missing threshold_pace_seconds_per_km"


# ── AC-no-pace: missing all pace data → null result ───────────────────────────

def test_missing_all_pace_data_returns_null_tss():
    """AC-no-pace: no splits and no avg pace → tss=None, method='none'."""
    result = calculate_pace_tss(
        splits=[],
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=3600,
        workout_avg_pace_seconds_per_km=None,
    )
    assert result["tss"] is None
    assert result["method"] == "none"


def test_missing_all_pace_data_debug_reason():
    """AC-no-pace: debug.reason is 'missing pace data'."""
    result = calculate_pace_tss(
        splits=None,
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=3600,
        workout_avg_pace_seconds_per_km=None,
    )
    assert result["debug"]["reason"] == "missing pace data"


# ── AC-return-shape: result always has required keys ──────────────────────────

def test_return_shape_success_case():
    """AC-return-shape: successful result has tss, method, debug keys."""
    result = calculate_pace_tss(
        splits=[_split(1080, 3.0)],
        threshold_pace_seconds_per_km=330,
        workout_duration_seconds=1080,
        workout_avg_pace_seconds_per_km=None,
    )
    assert "tss" in result
    assert "method" in result
    assert "debug" in result
    assert "laps" in result["debug"]


def test_return_shape_none_case():
    """AC-return-shape: null result still has tss, method, debug keys."""
    result = calculate_pace_tss(
        splits=[],
        threshold_pace_seconds_per_km=None,
        workout_duration_seconds=3600,
        workout_avg_pace_seconds_per_km=None,
    )
    assert "tss" in result
    assert "method" in result
    assert "debug" in result
