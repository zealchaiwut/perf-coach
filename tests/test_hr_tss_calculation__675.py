"""Tests for issue #675: Add pure HR-based TSS calculation function"""
from backend.services.tss import calculate_hr_tss


def test_hr_tss_60min_at_threshold():
    """AC: 60-min at threshold HR yields TSS = 100"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=160,
        threshold_hr=160,
        laps=None,
    )
    assert result["tss"] == 100
    assert result["method"] == "hr"
    assert result["debug"]["intensity_factor"] == 1.0
    assert result["debug"]["avg_hr_used"] == 160


def test_hr_tss_missing_threshold_hr():
    """AC: missing threshold_hr returns null + reason"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=160,
        threshold_hr=None,
        laps=None,
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "threshold_hr not set" in result["debug"]["reason"]


def test_hr_tss_zero_threshold_hr():
    """AC: zero threshold_hr returns null + reason"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=160,
        threshold_hr=0,
        laps=None,
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "threshold_hr is zero" in result["debug"]["reason"]


def test_hr_tss_missing_avg_hr():
    """AC: missing avg_hr returns null + reason"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=None,
        threshold_hr=160,
        laps=None,
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "avg_hr is missing" in result["debug"]["reason"]


def test_hr_tss_zero_avg_hr():
    """AC: zero avg_hr returns null + reason"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=0,
        threshold_hr=160,
        laps=None,
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "avg_hr is missing or zero" in result["debug"]["reason"]


def test_hr_tss_per_lap_avg_hr():
    """AC: per-lap avg_hr used when laps are present"""
    laps = [
        {"avg_hr": 150, "duration_seconds": 1800},  # 30 min at 150 bpm
        {"avg_hr": 170, "duration_seconds": 1800},  # 30 min at 170 bpm
    ]
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=155,  # This should not be used
        threshold_hr=160,
        laps=laps,
    )
    assert result["tss"] is not None
    assert result["method"] == "hr"
    # Lap 1: (1800/3600) * (150/160)^2 * 100 ≈ 43.95
    # Lap 2: (1800/3600) * (170/160)^2 * 100 ≈ 56.27
    # Total ≈ 100.22 → rounds to 100
    assert result["tss"] == 100
    # Weighted average: (150*1800 + 170*1800) / 3600 = 160
    assert result["debug"]["avg_hr_used"] == 160.0


def test_hr_tss_result_is_integer():
    """AC: returned tss value is a whole number (integer), not a float"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=165,
        threshold_hr=160,
        laps=None,
    )
    assert isinstance(result["tss"], int)
    assert result["tss"] > 0


def test_hr_tss_debug_shape():
    """AC: return shape includes all required debug fields"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=160,
        threshold_hr=160,
        laps=None,
    )
    assert "tss" in result
    assert "method" in result
    assert "debug" in result
    debug = result["debug"]
    assert "intensity_factor" in debug
    assert "avg_hr_used" in debug
    assert "threshold_hr" in debug
    assert "duration_seconds" in debug
    assert "duration_hours" in debug


def test_hr_tss_intensity_factor_formula():
    """AC: intensity_factor is computed as avg_hr / threshold_hr"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=180,
        threshold_hr=160,
        laps=None,
    )
    expected_if = 180 / 160
    assert abs(result["debug"]["intensity_factor"] - expected_if) < 0.001
    # TSS = 1.0 * (1.125)^2 * 100 ≈ 126.56 → rounds to 127
    assert result["tss"] == 127


def test_hr_tss_formula_accuracy():
    """AC: tss = (duration_seconds / 3600) × intensity_factor² × 100"""
    duration_seconds = 5400  # 90 minutes
    avg_hr = 150
    threshold_hr = 160
    result = calculate_hr_tss(
        duration_seconds=duration_seconds,
        avg_hr=avg_hr,
        threshold_hr=threshold_hr,
        laps=None,
    )
    # Manual calculation:
    # IF = 150 / 160 = 0.9375
    # TSS = (5400 / 3600) * 0.9375^2 * 100 = 1.5 * 0.87890625 * 100 ≈ 131.84
    expected_tss = round((duration_seconds / 3600) * (avg_hr / threshold_hr) ** 2 * 100)
    assert result["tss"] == expected_tss


def test_hr_tss_missing_duration_seconds():
    """AC: missing duration_seconds returns null + reason"""
    result = calculate_hr_tss(
        duration_seconds=None,
        avg_hr=160,
        threshold_hr=160,
        laps=None,
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "duration_seconds is missing" in result["debug"]["reason"]


def test_hr_tss_short_duration():
    """AC: short duration (< 1 minute) computes TSS correctly"""
    result = calculate_hr_tss(
        duration_seconds=600,  # 10 minutes
        avg_hr=160,
        threshold_hr=160,
        laps=None,
    )
    # TSS = (600 / 3600) * 1.0^2 * 100 ≈ 16.67 → rounds to 17
    assert result["tss"] == 17
    assert result["method"] == "hr"


def test_hr_tss_high_intensity():
    """AC: high intensity (HR > threshold) computes TSS correctly"""
    result = calculate_hr_tss(
        duration_seconds=3600,  # 60 minutes
        avg_hr=190,  # Above threshold
        threshold_hr=160,
        laps=None,
    )
    # IF = 190 / 160 = 1.1875
    # TSS = 1.0 * 1.1875^2 * 100 ≈ 140.89 → rounds to 141
    assert result["tss"] == 141
    assert result["debug"]["intensity_factor"] > 1.0


def test_hr_tss_low_intensity():
    """AC: low intensity (HR < threshold) computes TSS correctly"""
    result = calculate_hr_tss(
        duration_seconds=3600,  # 60 minutes
        avg_hr=130,  # Below threshold
        threshold_hr=160,
        laps=None,
    )
    # IF = 130 / 160 = 0.8125
    # TSS = 1.0 * 0.8125^2 * 100 ≈ 66.02 → rounds to 66
    assert result["tss"] == 66
    assert result["debug"]["intensity_factor"] < 1.0


def test_hr_tss_per_lap_partial_data():
    """AC: per-lap data with missing HR in one lap falls back to workout avg_hr"""
    laps = [
        {"avg_hr": 150, "duration_seconds": 1800},
        {"avg_hr": None, "duration_seconds": 1800},  # Missing HR
    ]
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=160,  # Falls back to this
        threshold_hr=160,
        laps=laps,
    )
    assert result["method"] == "hr"
    assert result["debug"]["avg_hr_used"] == 160


def test_hr_tss_per_lap_empty_list():
    """AC: empty laps list falls back to workout avg_hr"""
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=160,
        threshold_hr=160,
        laps=[],
    )
    assert result["method"] == "hr"
    assert result["tss"] == 100


def test_hr_tss_docstring_example():
    """AC: docstring worked example is accurate (60 min at threshold = 100)"""
    # From docstring: threshold_hr=170, avg_hr=170, duration_seconds=3600
    result = calculate_hr_tss(
        duration_seconds=3600,
        avg_hr=170,
        threshold_hr=170,
        laps=None,
    )
    assert result["tss"] == 100
    assert result["method"] == "hr"
    assert result["debug"]["intensity_factor"] == 1.0
