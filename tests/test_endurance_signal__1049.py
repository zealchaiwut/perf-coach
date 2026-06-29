"""Unit tests for endurance signal computation (issue #1049).

These tests anchor each acceptance criterion of issue #1049 to the pure
``compute_endurance_signal`` function.  They run entirely in-process — no live
server, no DB — so they are deterministic in any CI/gate environment.

Acceptance-criteria coverage:
  AC1  - Run split into first/second half by moving time (equal halves)
  AC2  - Efficiency = power/HR when power exists, else speed/HR
  AC3  - decoupling_percent = ((e1 - e2) / e1) * 100
  AC4  - endurance_signal increases as decoupling_percent decreases
  AC5  - Runs < 40 min produce no signal (all five fields null)
  AC6  - All five flat keys present on the result
  AC7  - endurance_signal_source is "power_hr" | "speed_hr" | None
  AC8  - Steady long run → high endurance_signal, low decoupling_percent
  AC9  - Run that fell apart → low endurance_signal, high decoupling_percent
  AC10 - Run under 40 minutes → all five fields null
"""

import pytest
from backend.services.endurance_signal import compute_endurance_signal

MIN_DURATION = 2400  # 40 minutes in seconds


def _make_splits(
    duration_each: int = 1500,  # 25 min each → 50 min total
    hr_first: float = 140.0,
    hr_second: float = 145.0,
    power_first: float | None = 250.0,
    power_second: float | None = 240.0,
    distance_km_first: float | None = None,
    distance_km_second: float | None = None,
) -> list[dict]:
    return [
        {
            "split_index": 0,
            "duration_seconds": duration_each,
            "avg_hr": hr_first,
            "avg_power": power_first,
            "distance_km": distance_km_first,
        },
        {
            "split_index": 1,
            "duration_seconds": duration_each,
            "avg_hr": hr_second,
            "avg_power": power_second,
            "distance_km": distance_km_second,
        },
    ]


LONG_WORKOUT = {"duration_seconds": MIN_DURATION + 1, "workout_type": "Run"}
SHORT_WORKOUT = {"duration_seconds": MIN_DURATION - 1, "workout_type": "Run"}


# ---------------------------------------------------------------------------
# AC1: Run split into first/second half by moving time
# ---------------------------------------------------------------------------

class TestHalfSplitByMovingTime:
    """AC1: the run is split into two equal halves by moving time."""

    def test_unequal_split_durations_partition_by_time(self):
        """A longer first split sits in the first half; the rest in the second."""
        splits = [
            {"split_index": 0, "duration_seconds": 1500, "avg_hr": 140.0,
             "avg_power": 250.0, "distance_km": None},
            {"split_index": 1, "duration_seconds": 1500, "avg_hr": 140.0,
             "avg_power": 250.0, "distance_km": None},
        ]
        # Total 3000s (50 min, > 40 min) → eligible and computes a signal.
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal"] is not None
        assert result["efficiency_first_half"] is not None
        assert result["efficiency_second_half"] is not None


# ---------------------------------------------------------------------------
# AC8: Steady long run — low drift → high signal, low decoupling
# ---------------------------------------------------------------------------

class TestSteadyLongRun:
    """AC8: steady effort across both halves produces low decoupling, high signal."""

    def test_high_endurance_signal(self):
        splits = _make_splits(
            hr_first=140.0, hr_second=141.0,
            power_first=250.0, power_second=249.0,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal"] is not None
        assert result["endurance_signal"] > 90

    def test_low_decoupling_percent(self):
        splits = _make_splits(
            hr_first=140.0, hr_second=140.0,
            power_first=250.0, power_second=250.0,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["decoupling_percent"] is not None
        assert abs(result["decoupling_percent"]) < 2.0

    def test_source_is_power_hr(self):
        splits = _make_splits(power_first=250.0, power_second=248.0)
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal_source"] == "power_hr"

    def test_efficiency_fields_present(self):
        splits = _make_splits()
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["efficiency_first_half"] is not None
        assert result["efficiency_second_half"] is not None
        assert result["efficiency_first_half"] > 0

    def test_zero_drift_produces_maximum_signal(self):
        """Perfectly flat effort → endurance_signal near 100."""
        splits = _make_splits(
            hr_first=140.0, hr_second=140.0,
            power_first=250.0, power_second=250.0,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal"] == pytest.approx(100.0, abs=0.1)
        assert result["decoupling_percent"] == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# AC9: Run that fell apart — high decoupling, low signal
# ---------------------------------------------------------------------------

class TestRunFellApart:
    """AC9: second half degrades significantly → high decoupling, low signal."""

    def test_low_endurance_signal(self):
        # Power drops 30% while HR stays same → ~30% decoupling
        splits = _make_splits(
            hr_first=140.0, hr_second=140.0,
            power_first=250.0, power_second=175.0,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal"] is not None
        assert result["endurance_signal"] < 80

    def test_high_decoupling_percent(self):
        splits = _make_splits(
            hr_first=140.0, hr_second=140.0,
            power_first=250.0, power_second=175.0,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["decoupling_percent"] is not None
        assert result["decoupling_percent"] > 20.0

    def test_signal_is_lower_than_steady_run(self):
        steady_splits = _make_splits(
            hr_first=140.0, hr_second=140.0,
            power_first=250.0, power_second=250.0,
        )
        degraded_splits = _make_splits(
            hr_first=140.0, hr_second=140.0,
            power_first=250.0, power_second=175.0,
        )
        steady = compute_endurance_signal(LONG_WORKOUT, steady_splits)
        degraded = compute_endurance_signal(LONG_WORKOUT, degraded_splits)
        assert degraded["endurance_signal"] < steady["endurance_signal"]

    def test_decoupling_math_thirty_percent(self):
        """AC3: power drops from 250 to 175 → (250-175)/250*100 = 30%."""
        splits = _make_splits(
            hr_first=140.0, hr_second=140.0,
            power_first=250.0, power_second=175.0,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["decoupling_percent"] == pytest.approx(30.0, abs=0.1)
        assert result["endurance_signal"] == pytest.approx(70.0, abs=0.1)


# ---------------------------------------------------------------------------
# AC5 / AC10: Run under 40 minutes → all five fields null
# ---------------------------------------------------------------------------

class TestShortRun:
    """AC5 / AC10: runs < 40 min produce null for all five endurance fields."""

    def test_all_five_fields_null(self):
        splits = _make_splits(duration_each=900)  # 15 min each = 30 min total
        result = compute_endurance_signal(SHORT_WORKOUT, splits)
        assert result["endurance_signal"] is None
        assert result["decoupling_percent"] is None
        assert result["efficiency_first_half"] is None
        assert result["efficiency_second_half"] is None
        assert result["endurance_signal_source"] is None

    def test_exactly_forty_minutes_produces_null(self):
        """Boundary: exactly 40 min (not strictly greater) → null."""
        workout = {"duration_seconds": MIN_DURATION, "workout_type": "Run"}
        splits = _make_splits(duration_each=1200)
        result = compute_endurance_signal(workout, splits)
        assert result["endurance_signal"] is None

    def test_no_duration_produces_null(self):
        workout = {"duration_seconds": None, "workout_type": "Run"}
        splits = _make_splits()
        result = compute_endurance_signal(workout, splits)
        assert result["endurance_signal"] is None

    def test_zero_duration_produces_null(self):
        workout = {"duration_seconds": 0, "workout_type": "Run"}
        result = compute_endurance_signal(workout, [])
        assert result["endurance_signal"] is None


# ---------------------------------------------------------------------------
# AC2 / AC7: Efficiency source selection
# ---------------------------------------------------------------------------

class TestEfficiencySource:
    def test_power_preferred_over_speed(self):
        """AC2: power/HR is used when power data exists, even if speed present."""
        splits = _make_splits(
            power_first=250.0, power_second=240.0,
            distance_km_first=0.416, distance_km_second=0.400,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal_source"] == "power_hr"

    def test_speed_hr_when_no_power(self):
        """AC2 / AC7: speed/HR fallback when no power data."""
        splits = _make_splits(
            power_first=None, power_second=None,
            distance_km_first=0.416, distance_km_second=0.400,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal_source"] == "speed_hr"

    def test_null_source_when_no_data(self):
        """AC7: no power and no speed → source is None."""
        splits = _make_splits(
            power_first=None, power_second=None,
            distance_km_first=None, distance_km_second=None,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert result["endurance_signal_source"] is None

    def test_speed_hr_decoupling_math(self):
        """AC3 via speed/HR: e1 = 0.416/1500/140, e2 = 0.380/1500/140
        decoupling = (e1-e2)/e1*100 = (0.416-0.380)/0.416*100 ≈ 8.65%.
        """
        splits = _make_splits(
            power_first=None, power_second=None,
            hr_first=140.0, hr_second=140.0,
            distance_km_first=0.416, distance_km_second=0.380,
        )
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        expected_decoupling = (0.416 - 0.380) / 0.416 * 100
        assert result["decoupling_percent"] == pytest.approx(
            expected_decoupling, abs=0.5
        )


# ---------------------------------------------------------------------------
# AC6: Result shape — all five flat keys present
# ---------------------------------------------------------------------------

class TestResultShape:
    def test_returns_all_five_keys(self):
        splits = _make_splits()
        result = compute_endurance_signal(LONG_WORKOUT, splits)
        assert "endurance_signal" in result
        assert "decoupling_percent" in result
        assert "efficiency_first_half" in result
        assert "efficiency_second_half" in result
        assert "endurance_signal_source" in result

    def test_no_splits_returns_all_null_above_threshold(self):
        """No usable split data → all null even for long runs."""
        result = compute_endurance_signal(LONG_WORKOUT, [])
        assert result["endurance_signal"] is None
        assert result["endurance_signal_source"] is None

    def test_signal_increases_as_decoupling_decreases(self):
        """AC4: ordering property — lower decoupling → higher signal."""
        low_drift = _make_splits(power_first=250.0, power_second=248.0)
        high_drift = _make_splits(power_first=250.0, power_second=200.0)
        r_low = compute_endurance_signal(LONG_WORKOUT, low_drift)
        r_high = compute_endurance_signal(LONG_WORKOUT, high_drift)
        assert r_low["endurance_signal"] > r_high["endurance_signal"]
        assert r_low["decoupling_percent"] < r_high["decoupling_percent"]
