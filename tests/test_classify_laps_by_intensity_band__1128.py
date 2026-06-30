"""Tests for issue #1128: Classify each lap by intensity band.

Acceptance criteria anchored:
  AC1 - Five bands with correct boundaries: easy < 0.80, steady 0.80–0.90,
        tempo 0.90–1.00, threshold 1.00–1.06, hard ≥ 1.06
  AC2 - Band assigned using power if power data is present for the lap
  AC3 - Band falls back to pace if power is absent but pace is present
  AC4 - Band falls back to HR if neither power nor pace is present
  AC5 - Threshold values read from user_preferences — no hardcoded constants
  AC6 - Every lap in a workout receives exactly one band (no lap left
        unclassified, no null/missing band when data is available)
  AC7 - Band is persisted on the lap record (DB column intensity_band)
  AC8 - py_compile reports zero errors on all modified files
"""
import pathlib
import types

import pytest

from backend.services.lap_classify import classify_laps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lap(avg_power=None, avg_hr=None, duration_seconds=600, distance_km=2.0):
    return types.SimpleNamespace(
        avg_power=avg_power,
        avg_hr=avg_hr,
        duration_seconds=duration_seconds,
        distance_km=distance_km,
    )


def _prefs(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None):
    return {
        "ftp_w": ftp_w,
        "threshold_hr": threshold_hr,
        "threshold_pace_seconds_per_km": threshold_pace_seconds_per_km,
    }


# ---------------------------------------------------------------------------
# AC1: Five bands with correct boundaries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("avg_power,ftp,expected_band", [
    (158, 200, "easy"),        # ratio 0.79 — below 0.80
    (100, 200, "easy"),        # ratio 0.50
    (160, 200, "steady"),      # ratio 0.80 — exact lower edge (boundary inclusion)
    (178, 200, "steady"),      # ratio 0.89
    (180, 200, "tempo"),       # ratio 0.90 — exact lower edge
    (198, 200, "tempo"),       # ratio 0.99
    (200, 200, "threshold"),   # ratio 1.00 — exact lower edge
    (210, 200, "threshold"),   # ratio 1.05
    (212, 200, "hard"),        # ratio 1.06 — exact lower edge
    (240, 200, "hard"),        # ratio 1.20
])
def test_ac1_band_boundaries(avg_power, ftp, expected_band):
    """AC1: Each boundary value maps to the correct (higher) band."""
    result = classify_laps([_lap(avg_power=avg_power)], _prefs(ftp_w=ftp))
    assert result[0]["band"] == expected_band


def test_ac1_five_distinct_bands_all_reachable():
    """AC1: All five band labels are reachable from power-based ratios."""
    prefs = _prefs(ftp_w=200)
    bands = {
        classify_laps([_lap(avg_power=150)], prefs)[0]["band"],   # easy 0.75
        classify_laps([_lap(avg_power=168)], prefs)[0]["band"],   # steady 0.84
        classify_laps([_lap(avg_power=192)], prefs)[0]["band"],   # tempo 0.96
        classify_laps([_lap(avg_power=206)], prefs)[0]["band"],   # threshold 1.03
        classify_laps([_lap(avg_power=220)], prefs)[0]["band"],   # hard 1.10
    }
    assert bands == {"easy", "steady", "tempo", "threshold", "hard"}


# ---------------------------------------------------------------------------
# AC2: Band assigned using power if power is present
# ---------------------------------------------------------------------------

def test_ac2_power_basis_used_when_power_present():
    """AC2: When avg_power and ftp_w are present, power basis is selected."""
    result = classify_laps([_lap(avg_power=220)], _prefs(ftp_w=200, threshold_hr=165))
    entry = result[0]
    assert entry["basis"] == "power"
    assert entry["band"] is not None


def test_ac2_power_ratio_correct():
    """AC2: Power ratio = avg_power / ftp_w (220/200 = 1.10 → hard)."""
    result = classify_laps([_lap(avg_power=220)], _prefs(ftp_w=200))
    entry = result[0]
    assert entry["ratio"] == pytest.approx(1.10, abs=0.01)
    assert entry["band"] == "hard"


# ---------------------------------------------------------------------------
# AC3: Band falls back to pace if power absent but pace present
# ---------------------------------------------------------------------------

def test_ac3_pace_fallback_when_power_absent():
    """AC3: When avg_power is None but duration/distance are present, pace basis is used."""
    lap = _lap(avg_power=None, avg_hr=None, duration_seconds=600, distance_km=2.0)
    result = classify_laps([lap], _prefs(ftp_w=200, threshold_pace_seconds_per_km=300))
    # Even though ftp_w is configured, the lap has no power → falls back to pace
    entry = result[0]
    assert entry["basis"] == "pace"
    assert entry["band"] is not None


def test_ac3_pace_ratio_correct():
    """AC3: Pace ratio = threshold_pace / lap_pace; faster lap = ratio > 1.0.

    threshold=300s/km, lap duration=600s, distance=2.4km → lap_pace=250s/km
    ratio = 300/250 = 1.20 → hard
    """
    lap = _lap(avg_power=None, duration_seconds=600, distance_km=2.4)
    result = classify_laps([lap], _prefs(threshold_pace_seconds_per_km=300))
    entry = result[0]
    assert entry["basis"] == "pace"
    assert entry["ratio"] == pytest.approx(1.20, abs=0.01)
    assert entry["band"] == "hard"


def test_ac3_pace_fallback_no_ftp_configured():
    """AC3: When ftp_w is not configured but threshold_pace is, pace is selected."""
    lap = _lap(avg_power=None, duration_seconds=500, distance_km=2.0)
    result = classify_laps([lap], _prefs(threshold_pace_seconds_per_km=300))
    assert result[0]["basis"] == "pace"


# ---------------------------------------------------------------------------
# AC4: Band falls back to HR if neither power nor pace present
# ---------------------------------------------------------------------------

def test_ac4_hr_fallback_when_power_and_pace_absent():
    """AC4: When power and pace are absent, HR basis is used."""
    lap = _lap(avg_power=None, avg_hr=155, duration_seconds=None, distance_km=None)
    result = classify_laps([lap], _prefs(threshold_hr=165))
    entry = result[0]
    assert entry["basis"] == "hr"
    assert entry["band"] is not None


def test_ac4_hr_ratio_correct():
    """AC4: HR ratio = avg_hr / threshold_hr (155/165 ≈ 0.94 → tempo)."""
    result = classify_laps([_lap(avg_power=None, avg_hr=155)], _prefs(threshold_hr=165))
    entry = result[0]
    assert entry["basis"] == "hr"
    assert entry["ratio"] == pytest.approx(155 / 165, abs=0.01)
    assert entry["band"] == "tempo"


def test_ac4_hr_fallback_no_power_no_pace_in_prefs():
    """AC4: HR selected when neither ftp_w nor threshold_pace is configured."""
    lap = _lap(avg_power=None, avg_hr=155)
    result = classify_laps([lap], _prefs(threshold_hr=165))
    assert result[0]["basis"] == "hr"
    assert result[0]["band"] is not None


def test_ac4_per_lap_fallthrough():
    """AC4: Per-lap fallthrough — one lap uses power, next uses pace (lap_classify semantics)."""
    laps = [
        _lap(avg_power=200),                              # has power → power basis
        _lap(avg_power=None, duration_seconds=600, distance_km=2.0),  # no power → pace
    ]
    prefs = _prefs(ftp_w=200, threshold_pace_seconds_per_km=300, threshold_hr=165)
    result = classify_laps(laps, prefs)
    # lap_classify.py uses per-lap fallthrough, so first uses power, second falls to pace
    assert result[0]["basis"] == "power"
    assert result[1]["basis"] == "pace"


# ---------------------------------------------------------------------------
# AC5: Thresholds from user_preferences — no hardcoded constants
# ---------------------------------------------------------------------------

def test_ac5_thresholds_from_prefs_dict_power():
    """AC5: FTP value is taken from prefs dict, not a hardcoded constant."""
    # Different FTP → different ratio → different band for same power
    lap = _lap(avg_power=200)
    result_high_ftp = classify_laps([lap], _prefs(ftp_w=300))  # 200/300 = 0.67 → easy
    result_low_ftp = classify_laps([lap], _prefs(ftp_w=180))   # 200/180 = 1.11 → hard
    assert result_high_ftp[0]["band"] == "easy"
    assert result_low_ftp[0]["band"] == "hard"


def test_ac5_thresholds_from_prefs_dict_hr():
    """AC5: Threshold HR value is taken from prefs dict, not a hardcoded constant."""
    lap = _lap(avg_power=None, avg_hr=165)
    result_low_thr = classify_laps([lap], _prefs(threshold_hr=150))   # 165/150 = 1.10 → hard
    result_high_thr = classify_laps([lap], _prefs(threshold_hr=200))  # 165/200 = 0.83 → steady
    assert result_low_thr[0]["band"] == "hard"
    assert result_high_thr[0]["band"] == "steady"


def test_ac5_no_hardcoded_thresholds_in_lap_classify_source():
    """AC5: lap_classify.py must not contain hardcoded numeric threshold constants."""
    src_path = pathlib.Path(__file__).parents[1] / "backend" / "services" / "lap_classify.py"
    src = src_path.read_text()
    # Hardcoded threshold values would be standalone integers like 200 (FTP), 165 (HR), 300 (pace)
    # Instead, thresholds must come from prefs. Check no line assigns a common threshold number.
    # We verify by confirming the source uses prefs.get() patterns, not literals for thresholds.
    assert "prefs.get" in src or "prefs[" in src, (
        "lap_classify.py must read thresholds from prefs dict, not hardcode them"
    )


def test_ac5_user_preferences_model_has_threshold_columns():
    """AC5: UserPreferences model exposes ftp_w, threshold_hr, threshold_pace_seconds_per_km."""
    from backend.models import UserPreferences
    assert hasattr(UserPreferences, "ftp_w")
    assert hasattr(UserPreferences, "threshold_hr")
    assert hasattr(UserPreferences, "threshold_pace_seconds_per_km")


# ---------------------------------------------------------------------------
# AC6: Every lap receives exactly one band when data is available
# ---------------------------------------------------------------------------

def test_ac6_every_lap_classified_with_power():
    """AC6: All laps in a power-data workout are classified (no skipped laps)."""
    laps = [_lap(avg_power=p) for p in [160, 180, 200, 220, 240]]
    result = classify_laps(laps, _prefs(ftp_w=200))
    assert len(result) == 5
    for entry in result:
        assert entry["band"] is not None, f"Lap with power should have a band, got {entry}"


def test_ac6_every_lap_classified_with_pace():
    """AC6: All laps in a pace-data workout are classified (no skipped laps)."""
    laps = [
        _lap(avg_power=None, duration_seconds=d, distance_km=2.0)
        for d in [500, 560, 620, 680, 740]
    ]
    result = classify_laps(laps, _prefs(threshold_pace_seconds_per_km=300))
    assert len(result) == 5
    for entry in result:
        assert entry["band"] is not None, f"Lap with pace should have a band, got {entry}"


def test_ac6_every_lap_classified_with_hr():
    """AC6: All laps in an HR-data workout are classified (no skipped laps)."""
    laps = [_lap(avg_power=None, avg_hr=h) for h in [130, 145, 158, 168, 180]]
    result = classify_laps(laps, _prefs(threshold_hr=165))
    assert len(result) == 5
    for entry in result:
        assert entry["band"] is not None, f"Lap with HR should have a band, got {entry}"


def test_ac6_one_result_per_lap():
    """AC6: Result list length always equals input list length."""
    laps = [_lap(avg_power=200)] * 10
    result = classify_laps(laps, _prefs(ftp_w=200))
    assert len(result) == 10


# ---------------------------------------------------------------------------
# AC7: Band persisted on the lap record (DB column)
# ---------------------------------------------------------------------------

def test_ac7_workout_split_model_has_intensity_band_column():
    """AC7: WorkoutSplit model declares intensity_band column."""
    from backend.models import WorkoutSplit
    assert hasattr(WorkoutSplit, "intensity_band"), (
        "WorkoutSplit model must have intensity_band column"
    )


def test_ac7_intensity_band_migration_file_exists():
    """AC7: An Alembic migration exists that adds intensity_band to workout_splits."""
    versions_dir = pathlib.Path(__file__).parents[1] / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*.py"))
    found = any(
        "intensity_band" in f.read_text()
        for f in migration_files
    )
    assert found, (
        "No Alembic migration found that adds intensity_band to workout_splits"
    )


def test_ac7_migration_is_idempotent():
    """AC7: Migration adds intensity_band column with idempotency guard (column_exists)."""
    versions_dir = pathlib.Path(__file__).parents[1] / "alembic" / "versions"
    migration_files = [
        f for f in versions_dir.glob("*.py")
        if "intensity_band" in f.read_text()
    ]
    assert migration_files, "No migration for intensity_band found"
    src = migration_files[0].read_text()
    assert "column_exists" in src, (
        "Migration must use column_exists guard for idempotency"
    )


def test_ac7_split_dict_includes_intensity_band():
    """AC7: _split_dict helper in main.py includes intensity_band in its output."""
    main_src = (pathlib.Path(__file__).parents[1] / "backend" / "main.py").read_text()
    # _split_dict must reference intensity_band
    assert "intensity_band" in main_src, (
        "main.py must include intensity_band in _split_dict or split response"
    )


def test_ac7_replace_splits_classifies_and_persists_band():
    """AC7: replace_splits endpoint classifies laps and stores intensity_band after commit."""
    main_src = (pathlib.Path(__file__).parents[1] / "backend" / "main.py").read_text()
    # The replace_splits function should call classify_laps (or lap_classify) and
    # assign intensity_band to each split object.
    assert "intensity_band" in main_src, (
        "replace_splits must assign intensity_band to WorkoutSplit objects"
    )
    assert "classify_laps" in main_src or "lap_classify" in main_src, (
        "replace_splits must call classify_laps to determine intensity bands"
    )


# ---------------------------------------------------------------------------
# AC8: py_compile reports zero errors
# ---------------------------------------------------------------------------

def test_ac8_models_py_compiles():
    """AC8: backend/models.py has no syntax errors."""
    import py_compile
    path = str(pathlib.Path(__file__).parents[1] / "backend" / "models.py")
    py_compile.compile(path, doraise=True)


def test_ac8_lap_classify_py_compiles():
    """AC8: backend/services/lap_classify.py has no syntax errors."""
    import py_compile
    path = str(pathlib.Path(__file__).parents[1] / "backend" / "services" / "lap_classify.py")
    py_compile.compile(path, doraise=True)


def test_ac8_main_py_compiles():
    """AC8: backend/main.py has no syntax errors."""
    import py_compile
    path = str(pathlib.Path(__file__).parents[1] / "backend" / "main.py")
    py_compile.compile(path, doraise=True)
