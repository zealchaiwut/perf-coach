from unittest.mock import patch

from backend.services.tss import (
    compute_tss,
    intensity_factor_from_pace,
    estimate_tss_for_workout,
)


def test_compute_tss_if_1_one_hour():
    assert compute_tss(1.0, 3600) == 100


def test_compute_tss_if_07_one_hour():
    assert compute_tss(0.7, 3600) == 49


def test_intensity_factor_from_pace_equal_threshold():
    p = 270.0
    assert intensity_factor_from_pace(p, p) == 1.0


def test_estimate_tss_prefers_power_over_pace():
    class MockWorkout:
        avg_power_w = 300
        avg_pace_seconds_per_km = 250
        duration_seconds = 3600
        avg_hr = None
        distance_km = None

    # Power is preferred when ftp_w is configured alongside pace threshold
    with patch("backend.services.tss.get_user_thresholds", return_value=(280, 170, 270)):
        _, method = estimate_tss_for_workout(MockWorkout())
    assert method == "power"


def test_estimate_tss_duration_only_fallback_when_no_intensity_data():
    class MockWorkout:
        avg_power_w = None
        avg_pace_seconds_per_km = None
        duration_seconds = 3600
        avg_hr = None
        distance_km = None

    tss, _ = estimate_tss_for_workout(MockWorkout())
    assert tss == 49


def test_estimate_tss_duration_only_returns_correct_method():
    class MockWorkout:
        avg_power_w = None
        avg_pace_seconds_per_km = None
        duration_seconds = 3600
        avg_hr = None
        distance_km = None

    _, method = estimate_tss_for_workout(MockWorkout())
    assert method == "duration_only"
