"""Tests for issue #674: Add pure running TSS pace calculation function.

Acceptance criteria covered:
  AC-signature        — function accepts threshold_pace_seconds_per_km, laps array
                        (each with lap_duration_seconds and lap_pace_seconds_per_km),
                        and optional whole_workout_average_pace_seconds_per_km
  AC-intensity        — lap_intensity = threshold / lap_pace (faster lap → intensity > 1)
  AC-lap-tss          — lap_tss = (lap_dur/3600) × intensity² × 100
  AC-sum-round        — tss = round(sum(lap_tss))
  AC-two-lap          — docstring worked example: threshold=300, lap1=600s/280pace,
                        lap2=900s/320pace → tss=41
  AC-single-lap       — single-lap split produces correct tss
  AC-fallback         — empty/absent laps fall back to whole_workout_average_pace
  AC-missing-threshold— threshold missing or zero → {tss:null, method:"none", reason:str, debug:null}
  AC-no-pace          — no laps and no fallback pace → {tss:null, method:"none", reason:str, debug:null}
  AC-return-shape-ok  — success: {tss:<int>, method:"pace", debug:{laps:[...]}}
  AC-return-shape-null— null: {tss:null, method:"none", reason:str, debug:null}
  AC-debug-laps       — debug.laps has per-lap dict with required keys
  AC-pace-at-threshold— pace == threshold → intensity=1.0, tss correct for duration
  AC-no-db            — file contains no SQLAlchemy / ORM imports
  AC-no-defaults      — no hardcoded threshold values in the pure function file
"""
import pathlib
import pytest

from backend.services.running_tss_pace import calculate_running_tss_pace


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lap(dur, pace):
    return {"lap_duration_seconds": dur, "lap_pace_seconds_per_km": pace}


# ── AC-two-lap: docstring worked example ──────────────────────────────────────

def test_docstring_two_lap_example_returns_41():
    """AC-two-lap: threshold=300, lap1=600s@280s/km, lap2=900s@320s/km → tss=41.

    Lap 1: intensity=300/280≈1.0714, lap_tss=(600/3600)×1.0714²×100≈19.13
    Lap 2: intensity=300/320=0.9375, lap_tss=(900/3600)×0.9375²×100≈21.97
    tss = round(19.13 + 21.97) = round(41.10) = 41
    """
    laps = [_lap(600, 280), _lap(900, 320)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    assert result["tss"] == 41
    assert result["method"] == "pace"


def test_two_lap_debug_has_two_entries():
    """AC-debug-laps: two-lap workout exposes two entries in debug.laps."""
    laps = [_lap(600, 280), _lap(900, 320)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    assert len(result["debug"]["laps"]) == 2


def test_faster_lap_intensity_exceeds_one():
    """AC-intensity: lap pace faster than threshold produces lap_intensity > 1."""
    # lap pace 280 s/km < threshold 300 s/km → intensity = 300/280 > 1
    laps = [_lap(600, 280)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    lap = result["debug"]["laps"][0]
    assert lap["lap_intensity"] > 1.0


def test_slower_lap_intensity_below_one():
    """AC-intensity: lap pace slower than threshold produces lap_intensity < 1."""
    # lap pace 320 s/km > threshold 300 s/km → intensity = 300/320 < 1
    laps = [_lap(900, 320)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    lap = result["debug"]["laps"][0]
    assert lap["lap_intensity"] < 1.0


# ── AC-single-lap ─────────────────────────────────────────────────────────────

def test_single_lap_at_threshold_gives_correct_tss():
    """AC-single-lap: 3600 s at threshold pace → tss=100."""
    laps = [_lap(3600, 300)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    assert result["tss"] == 100
    assert result["method"] == "pace"


def test_single_lap_below_threshold_tss_below_100():
    """AC-single-lap: 3600 s at slower pace → tss < 100."""
    laps = [_lap(3600, 360)]  # 360 s/km is slower than 300 threshold
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    assert result["tss"] < 100


# ── AC-pace-at-threshold: pace exactly equal to threshold ────────────────────

def test_pace_equal_to_threshold_intensity_is_one():
    """AC-pace-at-threshold: intensity_factor=1.0 when lap pace == threshold."""
    laps = [_lap(3600, 300)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    lap = result["debug"]["laps"][0]
    assert abs(lap["lap_intensity"] - 1.0) < 1e-9


def test_pace_equal_to_threshold_for_1h_gives_100():
    """AC-pace-at-threshold: 1 hour at exact threshold pace → tss=100."""
    laps = [_lap(3600, 300)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    assert result["tss"] == 100


# ── AC-fallback: no laps → use whole_workout_average_pace ────────────────────

def test_empty_laps_falls_back_to_avg_pace():
    """AC-fallback: empty laps list uses whole_workout_average_pace for a single synthetic lap."""
    # 3600 s at threshold pace → tss=100
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[],
        whole_workout_average_pace_seconds_per_km=300,
        total_duration_seconds=3600,
    )
    assert result["tss"] == 100
    assert result["method"] == "pace"


def test_none_laps_falls_back_to_avg_pace():
    """AC-fallback: laps=None is treated the same as empty list."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=None,
        whole_workout_average_pace_seconds_per_km=300,
        total_duration_seconds=3600,
    )
    assert result["tss"] == 100
    assert result["method"] == "pace"


def test_fallback_debug_has_one_synthetic_lap():
    """AC-debug-laps: fallback produces exactly one entry in debug.laps."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[],
        whole_workout_average_pace_seconds_per_km=300,
        total_duration_seconds=3600,
    )
    assert len(result["debug"]["laps"]) == 1


# ── AC-missing-threshold: threshold missing or zero ──────────────────────────

def test_threshold_none_returns_null_tss():
    """AC-missing-threshold: threshold_pace=None → tss=None, method='none'."""
    laps = [_lap(600, 280)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=None,
        laps=laps,
    )
    assert result["tss"] is None
    assert result["method"] == "none"


def test_threshold_zero_returns_null_tss():
    """AC-missing-threshold: threshold_pace=0 → tss=None, method='none'."""
    laps = [_lap(600, 280)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=0,
        laps=laps,
    )
    assert result["tss"] is None
    assert result["method"] == "none"


def test_threshold_none_reason_is_top_level():
    """AC-return-shape-null: null result has reason at top level (not inside debug)."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=None,
        laps=[_lap(600, 280)],
    )
    assert "reason" in result
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


def test_threshold_none_debug_is_null():
    """AC-return-shape-null: null result has debug=None."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=None,
        laps=[_lap(600, 280)],
    )
    assert result["debug"] is None


# ── AC-no-pace: missing all pace data → null result ──────────────────────────

def test_no_laps_no_fallback_returns_null_tss():
    """AC-no-pace: no laps and no avg pace → tss=None, method='none'."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[],
        whole_workout_average_pace_seconds_per_km=None,
    )
    assert result["tss"] is None
    assert result["method"] == "none"


def test_no_pace_reason_is_top_level():
    """AC-return-shape-null: no-pace null result has reason at top level."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=None,
        whole_workout_average_pace_seconds_per_km=None,
    )
    assert "reason" in result
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


def test_no_pace_debug_is_null():
    """AC-return-shape-null: no-pace null result has debug=None."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=None,
        whole_workout_average_pace_seconds_per_km=None,
    )
    assert result["debug"] is None


# ── AC-return-shape-ok: valid result shape ────────────────────────────────────

def test_valid_result_has_required_keys():
    """AC-return-shape-ok: valid result has tss, method, debug."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[_lap(600, 280)],
    )
    assert "tss" in result
    assert "method" in result
    assert "debug" in result


def test_valid_result_debug_has_laps_key():
    """AC-return-shape-ok: valid result debug contains laps array."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[_lap(600, 280)],
    )
    assert "laps" in result["debug"]
    assert isinstance(result["debug"]["laps"], list)


def test_tss_is_integer_on_success():
    """AC-sum-round: tss is a whole integer (not float) on success."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[_lap(600, 280)],
    )
    assert isinstance(result["tss"], int)


# ── AC-debug-laps: per-lap dict keys ─────────────────────────────────────────

def test_debug_lap_has_all_required_keys():
    """AC-debug-laps: each debug lap dict has lap_intensity, lap_tss, lap_duration_seconds, lap_pace_seconds_per_km."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[_lap(600, 280)],
    )
    lap = result["debug"]["laps"][0]
    assert "lap_intensity" in lap
    assert "lap_tss" in lap
    assert "lap_duration_seconds" in lap
    assert "lap_pace_seconds_per_km" in lap


def test_debug_lap_intensity_is_correct():
    """AC-intensity formula: lap_intensity = threshold / lap_pace."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[_lap(600, 280)],
    )
    lap = result["debug"]["laps"][0]
    expected_intensity = 300 / 280
    assert abs(lap["lap_intensity"] - expected_intensity) < 1e-9


def test_debug_lap_tss_is_correct():
    """AC-lap-tss formula: lap_tss = (dur/3600) × intensity² × 100."""
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=[_lap(600, 280)],
    )
    lap = result["debug"]["laps"][0]
    intensity = 300 / 280
    expected_lap_tss = (600 / 3600) * intensity ** 2 * 100
    assert abs(lap["lap_tss"] - expected_lap_tss) < 1e-6


def test_sum_of_lap_tss_rounds_to_tss():
    """AC-sum-round: tss equals round(sum of all lap_tss)."""
    laps = [_lap(600, 280), _lap(900, 320)]
    result = calculate_running_tss_pace(
        threshold_pace_seconds_per_km=300,
        laps=laps,
    )
    lap_sum = sum(lap["lap_tss"] for lap in result["debug"]["laps"])
    assert result["tss"] == round(lap_sum)


# ── AC-no-db: no ORM imports in the pure function file ───────────────────────

def test_function_file_has_no_orm_imports():
    """AC-no-db: running_tss_pace.py must not import SQLAlchemy or any ORM."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "running_tss_pace.py"
    code = src.read_text()
    assert "sqlalchemy" not in code.lower()
    assert "from backend.db" not in code
    assert "from backend.models" not in code


def test_function_file_has_no_db_calls():
    """AC-no-db: running_tss_pace.py must not call db.execute, session.query, etc."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "running_tss_pace.py"
    code = src.read_text()
    assert "db.execute" not in code
    assert "session.query" not in code
    assert ".fetchone" not in code
    assert ".fetchall" not in code


# ── AC-no-defaults: no hardcoded threshold in pure function file ──────────────

def test_function_file_has_no_hardcoded_threshold():
    """AC-no-defaults: running_tss_pace.py must not contain hardcoded threshold constants."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "running_tss_pace.py"
    code = src.read_text()
    # No numeric threshold default assignments (e.g. THRESHOLD_PACE = 270 or 300 or similar)
    assert "THRESHOLD_PACE" not in code
    assert "threshold_pace_seconds_per_km =" not in code.replace(" ", "").replace(
        "threshold_pace_seconds_per_km=None", ""
    ).replace("threshold_pace_seconds_per_km=threshold_pace_seconds_per_km", "")
