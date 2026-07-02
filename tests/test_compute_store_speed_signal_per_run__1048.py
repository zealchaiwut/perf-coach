"""Tests for issue #1048: Compute and store speed signal per run.

Acceptance criteria covered:

  AC1  - Scan windows of 1–6 minutes; select best effort using power/pace/HR.
  AC2  - speed_signal = best_short_effort / threshold_for_basis.
  AC3  - Run with no window meeting threshold band → speed_signal = null, not 0.
  AC4  - lap_classify.py is reused (no re-implementation of effort detection).
  AC5  - All four flat keys written: speed_signal, speed_signal_basis,
         speed_signal_window_seconds, speed_signal_source.
  AC6  - Basis falls back gracefully: power → pace → heart_rate.
  AC7  - Unit test: hard interval run → speed_signal > 0, all four keys populated.
  AC8  - Unit test: easy run with no lap at threshold → speed_signal = null,
         all three other keys also null.
"""

from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

VALID_BASES = {"power", "pace", "heart_rate"}
FOUR_KEYS = {"speed_signal", "speed_signal_basis", "speed_signal_window_seconds", "speed_signal_source"}


def _split(duration_seconds=300, avg_power=None, avg_hr=None, distance_km=None):
    """Build a SimpleNamespace that mimics a WorkoutSplit ORM row."""
    return SimpleNamespace(
        duration_seconds=duration_seconds,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
    )


def _hard_power_split(duration_seconds=300):
    """A 5-min split at 1.15×FTP (band=hard with ftp_w=200, avg_power=230)."""
    return _split(duration_seconds=duration_seconds, avg_power=230, avg_hr=165, distance_km=1.0)


def _easy_power_split(duration_seconds=600):
    """A 10-min split at 0.75×FTP (band=easy, out of window range at 600s)."""
    return _split(duration_seconds=duration_seconds, avg_power=150, avg_hr=130, distance_km=2.0)


def _easy_power_split_in_window(duration_seconds=300):
    """A 5-min split at 0.75×FTP (band=easy, inside window)."""
    return _split(duration_seconds=duration_seconds, avg_power=150, avg_hr=130, distance_km=1.5)


def _prefs_power(ftp_w=200):
    return {"ftp_w": ftp_w, "threshold_pace_seconds_per_km": None, "threshold_hr": None}


def _prefs_pace(threshold_pace=300):
    return {"ftp_w": None, "threshold_pace_seconds_per_km": threshold_pace, "threshold_hr": None}


def _prefs_hr(threshold_hr=165):
    return {"ftp_w": None, "threshold_pace_seconds_per_km": None, "threshold_hr": threshold_hr}


def _prefs_all(ftp_w=200, threshold_pace=300, threshold_hr=165):
    return {"ftp_w": ftp_w, "threshold_pace_seconds_per_km": threshold_pace, "threshold_hr": threshold_hr}


# ---------------------------------------------------------------------------
# AC1 – Module and function exist
# ---------------------------------------------------------------------------

class TestModuleAndFunctionExist:

    def test_module_importable(self):
        from backend.services import speed_signal  # noqa: F401

    def test_compute_speed_signal_importable(self):
        from backend.services.speed_signal import compute_speed_signal
        assert callable(compute_speed_signal)

    def test_compute_and_store_speed_signal_importable(self):
        from backend.services.speed_signal import compute_and_store_speed_signal
        assert callable(compute_and_store_speed_signal)


# ---------------------------------------------------------------------------
# AC5 – Return value always has exactly four keys
# ---------------------------------------------------------------------------

class TestReturnShape:

    def test_four_keys_on_success(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split()]
        result = compute_speed_signal(splits, _prefs_power())
        assert set(result.keys()) == FOUR_KEYS, f"Expected {FOUR_KEYS}, got {set(result.keys())}"

    def test_four_keys_when_no_qualifying_window(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_easy_power_split_in_window()]
        result = compute_speed_signal(splits, _prefs_power())
        assert set(result.keys()) == FOUR_KEYS, f"Expected {FOUR_KEYS}, got {set(result.keys())}"

    def test_four_keys_when_no_splits(self):
        from backend.services.speed_signal import compute_speed_signal
        result = compute_speed_signal([], _prefs_power())
        assert set(result.keys()) == FOUR_KEYS

    def test_four_keys_when_no_prefs(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split()]
        result = compute_speed_signal(splits, {})
        assert set(result.keys()) == FOUR_KEYS


# ---------------------------------------------------------------------------
# AC7 – Hard interval run → speed_signal > 0, all four keys populated
# ---------------------------------------------------------------------------

class TestHardIntervalRun:
    """AC7: hard interval run with laps above threshold → speed_signal > 0."""

    def test_speed_signal_positive_for_hard_run_power_basis(self):
        """avg_power=230, ftp_w=200 → ratio=1.15 → band='hard' → signal>0."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split(duration_seconds=300)]
        result = compute_speed_signal(splits, _prefs_power(ftp_w=200))
        assert result["speed_signal"] is not None
        assert result["speed_signal"] > 0, f"Expected signal>0, got {result['speed_signal']}"

    def test_speed_signal_at_least_1_for_threshold_effort(self):
        """Split at exactly threshold (ratio=1.0) → signal ≥ 1.0."""
        from backend.services.speed_signal import compute_speed_signal
        # avg_power=200, ftp_w=200 → ratio=1.00 → band='threshold'
        splits = [_split(duration_seconds=300, avg_power=200, avg_hr=165, distance_km=1.0)]
        result = compute_speed_signal(splits, _prefs_power(ftp_w=200))
        assert result["speed_signal"] is not None
        assert result["speed_signal"] >= 1.0, f"Expected signal≥1.0, got {result['speed_signal']}"

    def test_all_four_keys_populated_for_hard_run(self):
        """All four keys are non-null when a qualifying window exists."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split(duration_seconds=300)]
        result = compute_speed_signal(splits, _prefs_power(ftp_w=200))
        for key in FOUR_KEYS:
            assert result[key] is not None, f"Key '{key}' is null but should be populated"

    def test_speed_signal_basis_is_valid_string(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split()]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal_basis"] in VALID_BASES, (
            f"Expected one of {VALID_BASES}, got {result['speed_signal_basis']!r}"
        )

    def test_speed_signal_window_seconds_in_range(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split(duration_seconds=180)]
        result = compute_speed_signal(splits, _prefs_power())
        assert isinstance(result["speed_signal_window_seconds"], int)
        assert 60 <= result["speed_signal_window_seconds"] <= 360, (
            f"Window {result['speed_signal_window_seconds']}s not in [60, 360]"
        )

    def test_speed_signal_source_is_non_empty_string(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split()]
        result = compute_speed_signal(splits, _prefs_power())
        assert isinstance(result["speed_signal_source"], str)
        assert len(result["speed_signal_source"]) > 0

    def test_power_basis_used_when_ftp_and_power_available(self):
        """With ftp_w and avg_power, basis must be 'power'."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split()]
        result = compute_speed_signal(splits, _prefs_all())
        assert result["speed_signal_basis"] == "power"

    def test_best_window_selected_among_multiple_hard_laps(self):
        """Best (highest ratio) lap is selected when multiple hard laps exist."""
        from backend.services.speed_signal import compute_speed_signal
        # Two splits in window: one at 1.15× FTP, one at 1.30× FTP
        split_moderate = _split(duration_seconds=300, avg_power=230, avg_hr=165, distance_km=1.0)
        split_strong = _split(duration_seconds=240, avg_power=260, avg_hr=172, distance_km=0.9)
        result = compute_speed_signal([split_moderate, split_strong], _prefs_power(ftp_w=200))
        # 260/200=1.30 > 230/200=1.15 → stronger split wins
        assert result["speed_signal"] is not None
        assert result["speed_signal"] >= 1.30 - 0.01  # approx comparison (2 decimal places stored)

    def test_multiple_splits_only_best_counted(self):
        """Only the best qualifying window affects speed_signal."""
        from backend.services.speed_signal import compute_speed_signal
        # Mix easy and hard splits; the easy ones should not change the result
        hard = _split(duration_seconds=300, avg_power=230)
        easy = _split(duration_seconds=300, avg_power=150)
        result_hard_only = compute_speed_signal([hard], _prefs_power())
        result_mixed = compute_speed_signal([easy, hard, easy], _prefs_power())
        assert result_hard_only["speed_signal"] == result_mixed["speed_signal"]


# ---------------------------------------------------------------------------
# AC8 – Easy run → speed_signal = null and all three other keys also null
# ---------------------------------------------------------------------------

class TestEasyRun:
    """AC8: easy run with no window reaching threshold → all four keys null."""

    def test_speed_signal_null_for_easy_run(self):
        """avg_power=150, ftp_w=200 → ratio=0.75 → band='easy' → signal=null."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_easy_power_split_in_window()]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None, (
            f"Easy run should produce null signal, got {result['speed_signal']}"
        )

    def test_speed_signal_is_null_not_zero(self):
        """Explicitly verify that easy run stores None, not 0 or 0.0."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_easy_power_split_in_window()]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None  # not 0, not 0.0

    def test_speed_signal_basis_null_for_easy_run(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_easy_power_split_in_window()]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal_basis"] is None

    def test_speed_signal_window_seconds_null_for_easy_run(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_easy_power_split_in_window()]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal_window_seconds"] is None

    def test_speed_signal_source_null_for_easy_run(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_easy_power_split_in_window()]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal_source"] is None

    def test_all_four_keys_null_for_easy_run(self):
        """All four keys are null when no window reaches threshold band."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_easy_power_split_in_window()]
        result = compute_speed_signal(splits, _prefs_power())
        for key in FOUR_KEYS:
            assert result[key] is None, f"Key '{key}' should be null for easy run, got {result[key]!r}"


# ---------------------------------------------------------------------------
# AC3 – Null, not 0, when no threshold band reached
# ---------------------------------------------------------------------------

class TestNullVsZero:

    def test_no_splits_gives_all_nulls(self):
        from backend.services.speed_signal import compute_speed_signal
        result = compute_speed_signal([], _prefs_power())
        assert result["speed_signal"] is None

    def test_splits_outside_window_gives_null(self):
        """A 10-minute split (600s) is outside the 1–6 minute range → null."""
        from backend.services.speed_signal import compute_speed_signal
        # avg_power=230 → would be hard if in window, but duration=600s is too long
        splits = [_split(duration_seconds=600, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None

    def test_tempo_band_does_not_qualify(self):
        """Tempo (ratio 0.90–1.00) is below threshold band → null."""
        from backend.services.speed_signal import compute_speed_signal
        # avg_power=190, ftp_w=200 → ratio=0.95 → band='tempo'
        splits = [_split(duration_seconds=300, avg_power=190)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None

    def test_no_thresholds_in_prefs_gives_null(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_hard_power_split()]
        result = compute_speed_signal(splits, {})
        assert result["speed_signal"] is None

    def test_55_second_split_excluded(self):
        """A 55-second split is below the 60-second minimum → null."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=55, avg_power=250)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None

    def test_361_second_split_excluded(self):
        """A 361-second split is above the 360-second maximum → null."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=361, avg_power=250)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None

    def test_boundary_60_seconds_included(self):
        """A 60-second split exactly at the lower bound is included."""
        from backend.services.speed_signal import compute_speed_signal
        # avg_power=230, ftp_w=200 → ratio=1.15 → hard
        splits = [_split(duration_seconds=60, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is not None

    def test_boundary_360_seconds_included(self):
        """A 360-second split exactly at the upper bound is included."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=360, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is not None


# ---------------------------------------------------------------------------
# AC2 – speed_signal = best_short_effort / threshold_for_basis
# ---------------------------------------------------------------------------

class TestSignalFormula:

    def test_power_signal_equals_avg_power_over_ftp(self):
        """signal = avg_power / ftp_w (rounded to 2dp, matching classify_laps)."""
        from backend.services.speed_signal import compute_speed_signal
        # 220 / 200 = 1.10
        splits = [_split(duration_seconds=300, avg_power=220)]
        result = compute_speed_signal(splits, _prefs_power(ftp_w=200))
        assert result["speed_signal"] is not None
        assert abs(result["speed_signal"] - 1.10) < 0.01, (
            f"Expected ~1.10, got {result['speed_signal']}"
        )

    def test_hr_signal_equals_avg_hr_over_threshold_hr(self):
        """signal = avg_hr / threshold_hr when only HR basis is available."""
        from backend.services.speed_signal import compute_speed_signal
        # avg_hr=182, threshold_hr=165 → ratio=182/165=1.10
        splits = [_split(duration_seconds=300, avg_hr=182)]
        result = compute_speed_signal(splits, _prefs_hr(threshold_hr=165))
        assert result["speed_signal"] is not None
        expected = round(182 / 165, 2)
        assert abs(result["speed_signal"] - expected) < 0.01, (
            f"Expected ~{expected}, got {result['speed_signal']}"
        )

    def test_pace_signal_equals_threshold_pace_over_lap_pace(self):
        """signal = threshold_pace / lap_pace (inverted so faster = higher signal)."""
        from backend.services.speed_signal import compute_speed_signal
        # lap: 300s over 1.2km → pace=250 s/km
        # threshold_pace=300, signal=300/250=1.20
        splits = [_split(duration_seconds=300, distance_km=1.2)]
        result = compute_speed_signal(splits, _prefs_pace(threshold_pace=300))
        assert result["speed_signal"] is not None
        expected = round(300 / (300 / 1.2), 2)  # threshold / (dur/dist) = 300*1.2/300 = 1.20
        assert abs(result["speed_signal"] - expected) < 0.01, (
            f"Expected ~{expected}, got {result['speed_signal']}"
        )


# ---------------------------------------------------------------------------
# AC6 – Basis fallback: power → pace → heart_rate
# ---------------------------------------------------------------------------

class TestBasisFallback:

    def test_power_basis_when_ftp_available(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=300, avg_power=230, avg_hr=165, distance_km=1.0)]
        result = compute_speed_signal(splits, _prefs_all())
        assert result["speed_signal_basis"] == "power" or result["speed_signal"] is None

    def test_pace_basis_when_no_ftp_but_distance_available(self):
        """Without power data, falls back to pace when distance and threshold available."""
        from backend.services.speed_signal import compute_speed_signal
        # No avg_power, 300s over 1.2km → pace=250 s/km, threshold_pace=300 → ratio=1.2
        splits = [_split(duration_seconds=300, distance_km=1.2, avg_hr=175)]
        prefs = {"ftp_w": None, "threshold_pace_seconds_per_km": 300, "threshold_hr": 165}
        result = compute_speed_signal(splits, prefs)
        if result["speed_signal"] is not None:
            assert result["speed_signal_basis"] == "pace", (
                f"Expected 'pace' basis when no power data, got {result['speed_signal_basis']!r}"
            )

    def test_hr_basis_when_no_power_or_pace_threshold(self):
        """Falls back to heart_rate when power and pace thresholds are absent."""
        from backend.services.speed_signal import compute_speed_signal
        # avg_hr=182, threshold_hr=165 → ratio≈1.10 → 'threshold' band
        splits = [_split(duration_seconds=300, avg_hr=182)]
        result = compute_speed_signal(splits, _prefs_hr(threshold_hr=165))
        if result["speed_signal"] is not None:
            assert result["speed_signal_basis"] == "heart_rate", (
                f"Expected 'heart_rate', got {result['speed_signal_basis']!r}"
            )

    def test_pace_basis_string_is_pace_not_hr_label(self):
        """speed_signal_basis for pace is 'pace', not 'hr' (internal label)."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=300, distance_km=1.2)]
        result = compute_speed_signal(splits, _prefs_pace(threshold_pace=300))
        if result["speed_signal_basis"] is not None:
            assert result["speed_signal_basis"] in {"pace", "power", "heart_rate"}

    def test_hr_basis_string_is_heart_rate_not_hr_label(self):
        """speed_signal_basis for HR is 'heart_rate', not 'hr' (internal label)."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=300, avg_hr=182)]
        result = compute_speed_signal(splits, _prefs_hr(threshold_hr=165))
        if result["speed_signal_basis"] is not None:
            assert result["speed_signal_basis"] != "hr", (
                "Internal 'hr' label must be mapped to 'heart_rate' in the output"
            )

    def test_basis_none_when_no_thresholds(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=300, avg_power=230, avg_hr=170, distance_km=1.0)]
        result = compute_speed_signal(splits, {})
        assert result["speed_signal_basis"] is None

    def test_null_when_ftp_set_but_no_avg_power_and_no_other_threshold(self):
        """FTP set but split has no avg_power and no pace/HR threshold → null."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=300)]  # no power, no distance, no HR
        result = compute_speed_signal(splits, {"ftp_w": 200})
        assert result["speed_signal"] is None


# ---------------------------------------------------------------------------
# AC4 – lap_classify.py is reused (no re-implementation of effort detection)
# ---------------------------------------------------------------------------

class TestLapClassifyReused:

    def test_classify_laps_imported_by_speed_signal_module(self):
        """speed_signal.py imports from lap_classify, confirming reuse."""
        import inspect
        from backend.services import speed_signal
        source = inspect.getsource(speed_signal)
        assert "lap_classify" in source, (
            "speed_signal.py must import from lap_classify to reuse effort detection"
        )

    def test_result_consistent_with_classify_laps_output(self):
        """Ratio from speed_signal matches the ratio produced by classify_laps."""
        from backend.services.speed_signal import compute_speed_signal
        from backend.services.lap_classify import classify_laps

        splits = [_split(duration_seconds=300, avg_power=220)]
        prefs = _prefs_power(ftp_w=200)

        signal_result = compute_speed_signal(splits, prefs)
        laps_result = classify_laps(splits, prefs)

        if signal_result["speed_signal"] is not None:
            # The ratio from lap_classify should match speed_signal value
            classify_ratio = laps_result[0]["ratio"]
            assert abs(signal_result["speed_signal"] - classify_ratio) < 0.001, (
                f"speed_signal {signal_result['speed_signal']} != classify ratio {classify_ratio}"
            )


# ---------------------------------------------------------------------------
# AC1 – Window range: 1–6 minutes scanned
# ---------------------------------------------------------------------------

class TestWindowRange:

    def test_1_minute_split_is_in_range(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=60, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is not None

    def test_6_minute_split_is_in_range(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=360, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is not None

    def test_59_second_split_is_excluded(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=59, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None

    def test_361_second_split_is_excluded(self):
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=361, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        assert result["speed_signal"] is None

    def test_window_seconds_reflects_actual_split_duration(self):
        """speed_signal_window_seconds matches the selected split's duration."""
        from backend.services.speed_signal import compute_speed_signal
        splits = [_split(duration_seconds=240, avg_power=230)]
        result = compute_speed_signal(splits, _prefs_power())
        if result["speed_signal"] is not None:
            assert result["speed_signal_window_seconds"] == 240

    def test_best_window_chosen_among_mixed_durations(self):
        """Best effort is selected regardless of which window length it comes from."""
        from backend.services.speed_signal import compute_speed_signal
        # 90-second split at 1.15× and 300-second split at 1.30×
        short = _split(duration_seconds=90, avg_power=230)   # ratio=1.15
        long_ = _split(duration_seconds=300, avg_power=260)  # ratio=1.30
        result = compute_speed_signal([short, long_], _prefs_power(ftp_w=200))
        assert result["speed_signal"] is not None
        assert result["speed_signal_window_seconds"] == 300  # 1.30 > 1.15


# ---------------------------------------------------------------------------
# AC5 – Model columns present (checked via model import)
# ---------------------------------------------------------------------------

class TestModelColumns:

    def test_workout_model_has_speed_signal_column(self):
        from backend.models import Workout
        assert hasattr(Workout, "speed_signal"), (
            "Workout model must have 'speed_signal' column"
        )

    def test_workout_model_has_speed_signal_basis_column(self):
        from backend.models import Workout
        assert hasattr(Workout, "speed_signal_basis")

    def test_workout_model_has_speed_signal_window_seconds_column(self):
        from backend.models import Workout
        assert hasattr(Workout, "speed_signal_window_seconds")

    def test_workout_model_has_speed_signal_source_column(self):
        from backend.models import Workout
        assert hasattr(Workout, "speed_signal_source")


# ---------------------------------------------------------------------------
# Manual-laps path (issue #1240): a Stryd run whose 1 km auto-splits are
# sub-threshold but whose manual-lap reps are hard → speed_signal populated
# from the manual laps, source annotated "manual-lap window".
# ---------------------------------------------------------------------------

class _FakeQuery:
    """Minimal SQLAlchemy-query stand-in: filter/order_by are no-ops, and
    first()/all() return the rows this query was seeded with."""

    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Dispatches session.query(Model) to seeded rows keyed by model name."""

    def __init__(self, rows_by_model):
        self._rows_by_model = rows_by_model

    def query(self, model):
        return _FakeQuery(self._rows_by_model.get(model.__name__, []))


class TestManualLapsPath:
    """The DB caller prefers manual-lap reps over sub-threshold auto-splits."""

    def _run(self, monkeypatch, auto_splits, manual_laps, ftp_w=279):
        from backend.models import (
            Workout,
            WorkoutSplit,
            UserPreferences,
            StrydActivity,
        )
        import backend.services.speed_signal as ss

        workout = SimpleNamespace(
            id="w-1",
            user_id="u-1",
            workout_type="run",
            stryd_activity_pk="sa-1",
            speed_signal="SENTINEL",
            speed_signal_basis="SENTINEL",
            speed_signal_window_seconds="SENTINEL",
            speed_signal_source="SENTINEL",
        )
        sta = SimpleNamespace(id="sa-1", streams_payload={"any": "payload"})
        prefs = SimpleNamespace(
            user_id="u-1",
            ftp_w=ftp_w,
            threshold_hr=None,
            threshold_pace_seconds_per_km=None,
        )
        session = _FakeSession({
            Workout.__name__: [workout],
            WorkoutSplit.__name__: auto_splits,
            StrydActivity.__name__: [sta],
            UserPreferences.__name__: [prefs],
        })
        # compute_manual_laps is imported inside the caller from
        # backend.services.stryd_laps — patch it there.
        monkeypatch.setattr(
            "backend.services.stryd_laps.compute_manual_laps",
            lambda streams: manual_laps,
        )
        ok, reason = ss.compute_and_store_speed_signal("w-1", session)
        return ok, reason, workout

    def test_manual_reps_hard_when_auto_splits_subthreshold(self, monkeypatch):
        # Auto-splits: ~7 min at 0.96×FTP → tempo/below-hard, and out of the
        # 6-min window anyway (avg reps+recovery). Manual reps: ~95 s at
        # ~1.30×FTP (363W / 279W) → hard, inside the window.
        auto = [
            _split(duration_seconds=447, avg_power=249, distance_km=1.0),
            _split(duration_seconds=414, avg_power=269, distance_km=1.0),
        ]
        manual = [
            {"duration_seconds": 95, "distance_km": 0.31, "avg_power": 363, "avg_hr": 168},
            {"duration_seconds": 90, "distance_km": 0.11, "avg_power": 150, "avg_hr": 130},
            {"duration_seconds": 98, "distance_km": 0.32, "avg_power": 365, "avg_hr": 169},
        ]
        ok, reason, w = self._run(monkeypatch, auto, manual)
        assert ok is True, reason
        assert w.speed_signal is not None
        assert w.speed_signal > 1.0
        assert w.speed_signal_basis == "power"
        assert 60 <= w.speed_signal_window_seconds <= 360
        assert "manual-lap" in (w.speed_signal_source or "")

    def test_falls_back_to_auto_splits_when_manual_reps_not_hard(self, monkeypatch):
        # A qualifying hard auto-split (5 min at 1.15×FTP) but easy manual laps
        # → the caller falls back to the auto-splits and still finds the signal.
        auto = [_split(duration_seconds=300, avg_power=int(279 * 1.15), distance_km=1.0)]
        manual = [
            {"duration_seconds": 95, "distance_km": 0.3, "avg_power": 150, "avg_hr": 130},
            {"duration_seconds": 90, "distance_km": 0.3, "avg_power": 148, "avg_hr": 128},
        ]
        ok, reason, w = self._run(monkeypatch, auto, manual)
        assert ok is True, reason
        assert w.speed_signal is not None
        assert w.speed_signal_basis == "power"
        # Auto-split fallback → source must NOT be tagged manual-lap.
        assert "manual-lap" not in (w.speed_signal_source or "")

    def test_easy_run_no_hard_anywhere_stays_null(self, monkeypatch):
        # Neither auto-splits nor manual laps reach threshold → null (no false
        # positive).
        auto = [_split(duration_seconds=300, avg_power=150, distance_km=1.5)]
        manual = [
            {"duration_seconds": 95, "distance_km": 0.3, "avg_power": 145, "avg_hr": 125},
        ]
        ok, reason, w = self._run(monkeypatch, auto, manual)
        assert ok is True, reason
        assert w.speed_signal is None
        assert w.speed_signal_basis is None
        assert w.speed_signal_window_seconds is None
        assert w.speed_signal_source is None
