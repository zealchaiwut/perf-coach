"""Unit tests for aerobic decoupling computation (issue #691).

Covers AC13 unit test matrix:
  - Normal case with power and HR (stream-based)
  - Normal case with speed (velocity) and HR (stream-based, no power)
  - Missing stream and insufficient laps → returns (None, reason)
  - Missing HR data → returns (None, reason)
  - Value exceeding user threshold → faded_late is True
"""

import pytest
from backend.services.aerobic_decoupling import compute_decoupling


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stream(
    duration_s: int = 600,
    hr_first: float = 140.0,
    hr_second: float = 145.0,
    power_first: float | None = 250.0,
    power_second: float | None = 240.0,
    speed_first: float | None = 3.0,
    speed_second: float | None = 2.9,
    n_per_half: int = 100,
) -> dict:
    """Build a minimal stream dict with n_per_half points in each half."""
    step = duration_s / (2 * n_per_half)
    time_data = [i * step for i in range(2 * n_per_half)]
    hr_data = [hr_first] * n_per_half + [hr_second] * n_per_half
    stream = {
        "time": {"data": time_data},
        "heartrate": {"data": hr_data},
    }
    if power_first is not None:
        stream["watts"] = {
            "data": [power_first] * n_per_half + [power_second] * n_per_half
        }
    if speed_first is not None:
        stream["velocity_smooth"] = {
            "data": [speed_first] * n_per_half + [speed_second] * n_per_half
        }
    return stream


def _make_splits(
    hr_first: float = 140.0,
    hr_second: float = 145.0,
    power_first: float | None = 250.0,
    power_second: float | None = 240.0,
    speed_kmh_first: float | None = None,
    speed_kmh_second: float | None = None,
    duration_each: int = 300,
) -> list[dict]:
    """Two-split list for testing split-based path."""
    # speed from km/h → distance_km per split
    def _dist(spd, dur):
        if spd is None:
            return None
        return round(spd * dur / 3600, 4)

    return [
        {
            "split_index": 0,
            "duration_seconds": duration_each,
            "avg_hr": hr_first,
            "avg_power": power_first,
            "distance_km": _dist(speed_kmh_first, duration_each),
        },
        {
            "split_index": 1,
            "duration_seconds": duration_each,
            "avg_hr": hr_second,
            "avg_power": power_second,
            "distance_km": _dist(speed_kmh_second, duration_each),
        },
    ]


WORKOUT_BASIC = {"workout_type": "Run", "duration_seconds": 600}


# ---------------------------------------------------------------------------
# AC13-1 Normal case: power + HR (stream)
# ---------------------------------------------------------------------------

class TestNormalCasePowerAndHR:
    def test_returns_result_not_none(self):
        stream = _make_stream(power_first=250.0, power_second=240.0)
        result, reason = compute_decoupling(
            WORKOUT_BASIC, stream, threshold=None)
        assert result is not None
        assert reason is None

    def test_decoupling_pct_is_float_two_decimals(self):
        stream = _make_stream(power_first=250.0, power_second=240.0,
                              hr_first=140.0, hr_second=140.0)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        pct = result["decoupling_pct"]
        assert isinstance(pct, float)
        assert round(pct, 2) == pct

    def test_uses_power_over_speed_when_both_present(self):
        # power/hr efficiency: first = 250/140, second = 240/140 → drift
        # speed/hr efficiency: first = 3.0/140, second = 3.0/140 → no drift
        # result should show drift (power used, not speed)
        stream = _make_stream(power_first=250.0, power_second=240.0,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=3.0, speed_second=3.0)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        # power-based: (250/140 - 240/140) / (250/140) * 100
        # = (10/140) / (250/140) * 100 = 10/250 * 100 = 4.0
        assert result["decoupling_pct"] == pytest.approx(4.0, abs=0.05)

    def test_debug_contains_both_efficiencies(self):
        stream = _make_stream(power_first=250.0, power_second=240.0)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        assert "first_half_efficiency" in result["debug"]
        assert "second_half_efficiency" in result["debug"]

    def test_faded_late_false_when_no_threshold(self):
        stream = _make_stream(power_first=250.0, power_second=200.0)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        assert result["faded_late"] is False

    def test_docstring_worked_example_five_percent(self):
        """AC9: first=1.00, second=0.95 → 5% decoupling."""
        # power_first/hr_first = 1.00 → e.g. 140/140
        # power_second/hr_second = 0.95 → e.g. 133/140
        stream = _make_stream(power_first=140.0, power_second=133.0,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=None, speed_second=None)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        assert result["decoupling_pct"] == pytest.approx(5.0, abs=0.1)


# ---------------------------------------------------------------------------
# AC13-2 Normal case: speed + HR (no power)
# ---------------------------------------------------------------------------

class TestNormalCaseSpeedAndHR:
    def test_returns_result_not_none(self):
        stream = _make_stream(power_first=None, power_second=None,
                              speed_first=3.0, speed_second=2.9)
        result, reason = compute_decoupling(
            WORKOUT_BASIC, stream, threshold=None)
        assert result is not None
        assert reason is None

    def test_decoupling_computed_from_speed(self):
        # speed/hr: first = 3.0/140, second = 2.85/140
        # decoupling = (3.0 - 2.85)/3.0 * 100 = 5.0
        stream = _make_stream(power_first=None, power_second=None,
                              speed_first=3.0, speed_second=2.85,
                              hr_first=140.0, hr_second=140.0)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        assert result["decoupling_pct"] == pytest.approx(5.0, abs=0.1)

    def test_debug_first_efficiency_speed_based(self):
        stream = _make_stream(power_first=None, power_second=None,
                              speed_first=3.0, speed_second=2.9,
                              hr_first=140.0, hr_second=140.0)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        # first_half_efficiency should be speed/hr = 3.0/140
        expected = 3.0 / 140.0
        assert result["debug"]["first_half_efficiency"] == pytest.approx(
            expected, rel=0.01)


# ---------------------------------------------------------------------------
# AC13-3 Missing stream and insufficient laps → null
# ---------------------------------------------------------------------------

class TestMissingStreamInsufficientLaps:
    def test_none_stream_returns_null(self):
        result, reason = compute_decoupling(
            WORKOUT_BASIC, None, threshold=None)
        assert result is None
        assert reason is not None
        assert len(reason) > 0

    def test_empty_stream_returns_null(self):
        result, reason = compute_decoupling(WORKOUT_BASIC, {}, threshold=None)
        assert result is None
        assert reason is not None

    def test_empty_list_returns_null(self):
        result, reason = compute_decoupling(WORKOUT_BASIC, [], threshold=None)
        assert result is None
        assert reason is not None

    def test_single_split_returns_null(self):
        """One lap → insufficient to split into two halves."""
        splits = [
            {"split_index": 0, "duration_seconds": 600,
                "avg_hr": 140, "avg_power": 250}
        ]
        result, reason = compute_decoupling(
            WORKOUT_BASIC, splits, threshold=None)
        assert result is None
        assert "insufficient" in reason.lower(
        ) or "lap" in reason.lower() or "split" in reason.lower()

    def test_reason_string_not_empty(self):
        result, reason = compute_decoupling(
            WORKOUT_BASIC, None, threshold=None)
        assert isinstance(reason, str)
        assert len(reason) > 0


# ---------------------------------------------------------------------------
# AC13-4 Missing HR data → null
# ---------------------------------------------------------------------------

class TestMissingHRData:
    def test_stream_no_hr_returns_null(self):
        """Stream with time + watts but no heartrate → null."""
        stream = {
            "time": {"data": list(range(200))},
            "watts": {"data": [250.0] * 200},
        }
        result, reason = compute_decoupling(
            WORKOUT_BASIC, stream, threshold=None)
        assert result is None
        assert reason is not None
        assert "heart" in reason.lower() or "hr" in reason.lower()

    def test_splits_no_hr_returns_null(self):
        """Splits without avg_hr → null."""
        splits = [
            {"split_index": 0, "duration_seconds": 300,
                "avg_hr": None, "avg_power": 250},
            {"split_index": 1, "duration_seconds": 300,
                "avg_hr": None, "avg_power": 240},
        ]
        result, reason = compute_decoupling(
            WORKOUT_BASIC, splits, threshold=None)
        assert result is None
        assert reason is not None


# ---------------------------------------------------------------------------
# AC13-5 Value exceeds threshold → faded_late True
# ---------------------------------------------------------------------------

class TestFadedLateThreshold:
    def test_faded_late_true_when_decoupling_exceeds_threshold(self):
        """AC6: decoupling > threshold → faded_late True."""
        # power drift: 250→220 with same HR 140 → (250-220)/250*100 = 12%
        stream = _make_stream(power_first=250.0, power_second=220.0,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=None, speed_second=None)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=5.0)
        assert result["faded_late"] is True

    def test_faded_late_false_when_decoupling_below_threshold(self):
        """decoupling < threshold → faded_late False."""
        # small drift: 250→248 → ~0.8%
        stream = _make_stream(power_first=250.0, power_second=248.0,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=None, speed_second=None)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=5.0)
        assert result["faded_late"] is False

    def test_faded_late_false_when_threshold_not_set(self):
        """No threshold set → faded_late defaults to False."""
        stream = _make_stream(power_first=250.0, power_second=200.0,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=None, speed_second=None)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=None)
        assert result["faded_late"] is False

    def test_faded_late_false_when_decoupling_equals_threshold(self):
        """Exactly at threshold (not strictly greater) → faded_late False."""
        # decoupling exactly 5.0%: power 250→237.5, hr 140/140
        # (250-237.5)/250 * 100 = 5.0
        stream = _make_stream(power_first=250.0, power_second=237.5,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=None, speed_second=None)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=5.0)
        assert result["faded_late"] is False

    def test_threshold_from_uат_step5(self):
        """UAT step 5: threshold=5, decoupling=7 → faded_late True (AC6)."""
        # Construct stream where decoupling ≈ 7%
        # power_first/hr = 250/140 = 1.7857
        # power_second/hr for 7% decay: 1.7857 * (1 - 0.07) = 1.6607
        # power_second = 1.6607 * 140 = 232.5
        stream = _make_stream(power_first=250.0, power_second=232.5,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=None, speed_second=None)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=5.0)
        assert result["decoupling_pct"] == pytest.approx(7.0, abs=0.1)
        assert result["faded_late"] is True

    def test_threshold_from_uат_step6(self):
        """UAT step 6: threshold=10, same 7% decoupling → faded_late False."""
        stream = _make_stream(power_first=250.0, power_second=232.5,
                              hr_first=140.0, hr_second=140.0,
                              speed_first=None, speed_second=None)
        result, _ = compute_decoupling(WORKOUT_BASIC, stream, threshold=10.0)
        assert result["faded_late"] is False


# ---------------------------------------------------------------------------
# Split-based path (two or more splits)
# ---------------------------------------------------------------------------

class TestSplitBasedPath:
    def test_two_splits_with_power(self):
        splits = _make_splits(hr_first=140, hr_second=145,
                              power_first=250, power_second=240)
        result, reason = compute_decoupling(
            WORKOUT_BASIC, splits, threshold=None)
        assert result is not None
        assert reason is None

    def test_two_splits_with_speed(self):
        splits = _make_splits(hr_first=140, hr_second=145,
                              power_first=None, power_second=None,
                              speed_kmh_first=12.0, speed_kmh_second=11.5)
        result, reason = compute_decoupling(
            WORKOUT_BASIC, splits, threshold=None)
        assert result is not None

    def test_split_result_contains_required_fields(self):
        splits = _make_splits()
        result, _ = compute_decoupling(WORKOUT_BASIC, splits, threshold=None)
        assert "decoupling_pct" in result
        assert "faded_late" in result
        assert "debug" in result
        assert "first_half_efficiency" in result["debug"]
        assert "second_half_efficiency" in result["debug"]

    def test_split_decoupling_pct_two_decimal_places(self):
        splits = _make_splits()
        result, _ = compute_decoupling(WORKOUT_BASIC, splits, threshold=None)
        pct = result["decoupling_pct"]
        assert round(pct, 2) == pct
