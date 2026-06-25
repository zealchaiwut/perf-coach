"""
Tests for issue #913: Fix empty Personal Records for athletes with run history.

AC1 — The PR endpoint caller logs: duration_curve_populated, runs_considered,
      records_returned.
AC3 — Athletes with extensive run history see real records (volume + speed + power).
AC4 — When a specific record cannot be computed, the result carries a non-empty
      'reason' string.
AC5 — Caller remains thin; pure detection functions in pr_detection.py are
      importable without any DB dependency.
AC6 — No hardcoded values; STANDARD_DISTANCES_KM / STANDARD_POWER_DURATIONS_SECONDS
      drive detection.
AC7 — New unit tests cover the logging path (_build_run_pr_log_entry); existing
      passing tests must not break.
"""
import unittest.mock as mock

import pytest

from backend.services.pr_detection import (
    STANDARD_DISTANCES_KM,
    STANDARD_POWER_DURATIONS_SECONDS,
    detect_power_records,
    detect_speed_records,
    detect_volume_records,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(id, date, distance_km, duration_seconds, tss=None, avg_power=None):
    return {
        "id": id,
        "workout_date": date,
        "distance_km": distance_km,
        "duration_seconds": duration_seconds,
        "tss": tss,
        "avg_power": avg_power,
        "workout_type": "Run",
    }


def _pace_point(duration_seconds, best_value, workout_id, date, source_workout=None):
    return {
        "duration_seconds": duration_seconds,
        "best_value": best_value,
        "source_workout_id": workout_id,
        "date": date,
        "source_workout": source_workout,
    }


def _power_point(duration_seconds, best_value, workout_id, date, source_workout=None):
    return {
        "duration_seconds": duration_seconds,
        "best_value": best_value,
        "source_workout_id": workout_id,
        "date": date,
        "source_workout": source_workout,
    }


def _make_mock_db(runs=None, curve_data=None):
    """Return a SQLAlchemy session mock. Passes through Workout and AthleteDurationCurve queries."""
    db = mock.MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = runs or []
    if curve_data is not None:
        curve_row = mock.MagicMock()
        curve_row.curve_data = curve_data
        db.get.return_value = curve_row
    else:
        db.get.return_value = None
    return db


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — Logging path: _build_run_pr_log_entry produces required fields
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildRunPrLogEntryRequiredFields:
    """_build_run_pr_log_entry must produce the three fields required by AC1."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from backend.main import _build_run_pr_log_entry

        run = _run("r1", "2026-01-10", 42.195, 14400)
        pace = 14400 / 42.195
        curve = [_pace_point(14400, pace, "r1", "2026-01-10", run)]
        self.records = {
            "speedRecords": detect_speed_records(curve, [run]),
            "powerRecords": detect_power_records([]),
            "volumeRecords": detect_volume_records([run]),
        }
        self.meta = {"duration_curve_populated": False, "runs_considered": 1}
        self.log_entry = _build_run_pr_log_entry(self.meta, self.records)

    def test_log_entry_has_duration_curve_populated(self):
        """AC1: log must contain duration_curve_populated."""
        assert "duration_curve_populated" in self.log_entry

    def test_log_entry_has_runs_considered(self):
        """AC1: log must contain runs_considered."""
        assert "runs_considered" in self.log_entry

    def test_log_entry_has_records_returned(self):
        """AC1: log must contain records_returned."""
        assert "records_returned" in self.log_entry

    def test_duration_curve_populated_is_bool(self):
        assert isinstance(self.log_entry["duration_curve_populated"], bool)

    def test_runs_considered_is_int(self):
        assert isinstance(self.log_entry["runs_considered"], int)

    def test_records_returned_is_int(self):
        assert isinstance(self.log_entry["records_returned"], int)

    def test_duration_curve_populated_value_matches_meta(self):
        assert self.log_entry["duration_curve_populated"] is False

    def test_runs_considered_value_matches_meta(self):
        assert self.log_entry["runs_considered"] == 1

    def test_records_returned_positive_for_run_with_distance(self):
        """Volume + speed records exist for the 42 km run, so count > 0."""
        assert self.log_entry["records_returned"] > 0

    def test_log_entry_has_event_field(self):
        assert self.log_entry.get("event") == "run_pr_detected"


class TestBuildRunPrLogEntryWithCurvePopulated:
    """Log entry reflects populated duration curve."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from backend.main import _build_run_pr_log_entry

        run = _run("r2", "2026-01-15", 5.0, 1300, avg_power=280)
        power_curve = [_power_point(1200, 280.0, "r2", "2026-01-15", run)]
        speed_curve = [_pace_point(1300, 1300 / 5.0, "r2", "2026-01-15", run)]
        self.records = {
            "speedRecords": detect_speed_records(speed_curve, [run]),
            "powerRecords": detect_power_records(power_curve),
            "volumeRecords": detect_volume_records([run]),
        }
        self.meta = {"duration_curve_populated": True, "runs_considered": 1}
        self.log_entry = _build_run_pr_log_entry(self.meta, self.records)

    def test_duration_curve_populated_true(self):
        assert self.log_entry["duration_curve_populated"] is True

    def test_records_returned_includes_power_records(self):
        """20-min power record exists in curve, so records_returned >= 1."""
        assert self.log_entry["records_returned"] >= 1


class TestBuildRunPrLogEntryZeroRuns:
    """Log entry when there are no runs (empty state — UAT step 4)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from backend.main import _build_run_pr_log_entry

        self.records = {
            "speedRecords": detect_speed_records([], []),
            "powerRecords": detect_power_records([]),
            "volumeRecords": detect_volume_records([]),
        }
        self.meta = {"duration_curve_populated": False, "runs_considered": 0}
        self.log_entry = _build_run_pr_log_entry(self.meta, self.records)

    def test_runs_considered_zero(self):
        """AC1 + UAT step 4: logs reflect runs_considered: 0 for empty history."""
        assert self.log_entry["runs_considered"] == 0

    def test_records_returned_zero(self):
        assert self.log_entry["records_returned"] == 0

    def test_duration_curve_populated_false(self):
        assert self.log_entry["duration_curve_populated"] is False


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — fetch_and_detect_records returns _meta for endpoint logging
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchAndDetectRecordsReturnsMetadata:
    """fetch_and_detect_records must return _meta so the endpoint can log it."""

    def _call(self, runs=None, curve_data=None):
        from backend.services.pr_detection import fetch_and_detect_records

        db = _make_mock_db(runs=runs, curve_data=curve_data)
        return fetch_and_detect_records(object(), db)

    def test_result_has_meta_key(self):
        result = self._call()
        assert "_meta" in result

    def test_meta_has_duration_curve_populated(self):
        result = self._call()
        assert "duration_curve_populated" in result["_meta"]

    def test_meta_has_runs_considered(self):
        result = self._call()
        assert "runs_considered" in result["_meta"]

    def test_meta_runs_considered_zero_for_empty_db(self):
        result = self._call(runs=[])
        assert result["_meta"]["runs_considered"] == 0

    def test_meta_curve_not_populated_when_no_curve_row(self):
        result = self._call(curve_data=None)
        assert result["_meta"]["duration_curve_populated"] is False

    def test_meta_curve_populated_when_curve_row_exists(self):
        result = self._call(curve_data={"60": {"best_value": 300.0, "workout_id": "x", "date": "2026-01-01"}})
        assert result["_meta"]["duration_curve_populated"] is True


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — Volume records for athletes with run history
# ══════════════════════════════════════════════════════════════════════════════

class TestVolumeRecordsReturnedForRunHistory:
    """Athletes with distance + duration on runs see volume PRs."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.runs = [
            _run("v1", "2026-01-10", 10.0, 3600, tss=60),
            _run("v2", "2026-01-12", 42.195, 14400, tss=120),
            _run("v3", "2026-01-15", 5.0, 1800, tss=35),
        ]
        self.result = detect_volume_records(self.runs)

    def test_longest_by_distance_present(self):
        assert "longestByDistance" in self.result
        assert "reason" not in self.result.get("longestByDistance", {})

    def test_longest_by_distance_is_marathon_distance(self):
        assert abs(self.result["longestByDistance"]["value"] - 42.195) < 0.01

    def test_longest_by_distance_has_source_workout(self):
        sw = self.result["longestByDistance"]["sourceWorkout"]
        assert sw is not None
        assert sw["id"] == "v2"

    def test_longest_by_distance_has_date(self):
        assert self.result["longestByDistance"]["date"] == "2026-01-12"


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — Fastest 5 km for athlete who covered 5+ km
# ══════════════════════════════════════════════════════════════════════════════

class TestSpeedRecordsFastestFiveKm:
    """AC3: a marathon run must produce a fastest 5 km record."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.run = _run("s1", "2026-01-20", 42.195, 14400)
        pace = 14400 / 42.195
        self.curve = [_pace_point(14400, pace, "s1", "2026-01-20", self.run)]
        self.result = detect_speed_records(self.curve, [self.run])

    def test_fastest_5km_present(self):
        assert "5km" in self.result
        assert "reason" not in self.result["5km"]
        assert "value" in self.result["5km"]

    def test_fastest_5km_has_date(self):
        assert self.result["5km"]["date"] == "2026-01-20"

    def test_fastest_5km_has_source_workout(self):
        assert self.result["5km"]["sourceWorkout"]["id"] == "s1"


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — Best 20-minute power from duration curve
# ══════════════════════════════════════════════════════════════════════════════

class TestBest20MinPower:
    """AC3: curve with 1200 s entry returns best20Min."""

    @pytest.fixture(autouse=True)
    def setup(self):
        run = _run("p1", "2026-02-01", 10.0, 3600, avg_power=290)
        self.curve = [
            _power_point(60, 350.0, "p1", "2026-02-01", run),
            _power_point(300, 310.0, "p1", "2026-02-01", run),
            _power_point(1200, 290.0, "p1", "2026-02-01", run),
        ]
        self.result = detect_power_records(self.curve)

    def test_best20min_present(self):
        assert "best20Min" in self.result
        assert "reason" not in self.result["best20Min"]

    def test_best20min_value(self):
        assert self.result["best20Min"]["value"] == 290.0

    def test_best20min_has_source_workout(self):
        assert self.result["best20Min"]["sourceWorkout"]["id"] == "p1"


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — Honest reason strings for missing records
# ══════════════════════════════════════════════════════════════════════════════

class TestHonestReasonForMissingRecords:
    """When data is insufficient, records carry a 'reason' instead of a blank."""

    def test_speed_marathon_missing_for_short_run(self):
        """A 5 km run cannot produce a marathon PR; reason explains why."""
        run = _run("hr1", "2026-01-01", 5.0, 1300)
        curve = [_pace_point(1300, 260.0, "hr1", "2026-01-01", run)]
        result = detect_speed_records(curve, [run])
        assert "reason" in result["marathon"]
        assert isinstance(result["marathon"]["reason"], str)
        assert len(result["marathon"]["reason"]) > 0

    def test_speed_reason_is_descriptive(self):
        """Reason string mentions distance or data."""
        run = _run("hr2", "2026-01-02", 5.0, 1300)
        curve = [_pace_point(1300, 260.0, "hr2", "2026-01-02", run)]
        result = detect_speed_records(curve, [run])
        reason = result["marathon"]["reason"].lower()
        assert any(word in reason for word in ("distance", "curve", "data", "km"))

    def test_power_reason_when_no_curve(self):
        """Empty power curve → top-level reason string."""
        result = detect_power_records([])
        assert "reason" in result
        assert isinstance(result["reason"], str)

    def test_power_1min_reason_when_only_20min_in_curve(self):
        """Only 20-min curve data → best1Min carries reason."""
        run = _run("hr3", "2026-01-03", 5.0, 1300, avg_power=280)
        curve = [_power_point(1200, 280.0, "hr3", "2026-01-03", run)]
        result = detect_power_records(curve)
        assert "reason" in result["best1Min"]
        assert "value" not in result["best1Min"]

    def test_volume_reason_when_no_runs(self):
        """Empty run list → top-level reason string."""
        result = detect_volume_records([])
        assert "reason" in result
        assert isinstance(result["reason"], str)


# ══════════════════════════════════════════════════════════════════════════════
# AC5 — Pure detection functions importable without DB
# ══════════════════════════════════════════════════════════════════════════════

class TestPureDetectionFunctionsNeedNoDb:
    """Pure detection functions must be importable and callable without DB setup."""

    def test_detect_speed_records_callable(self):
        assert callable(detect_speed_records)

    def test_detect_power_records_callable(self):
        assert callable(detect_power_records)

    def test_detect_volume_records_callable(self):
        assert callable(detect_volume_records)

    def test_speed_records_returns_dict_not_exception(self):
        result = detect_speed_records([], [])
        assert isinstance(result, dict)

    def test_power_records_returns_dict_not_exception(self):
        result = detect_power_records([])
        assert isinstance(result, dict)

    def test_volume_records_returns_dict_not_exception(self):
        result = detect_volume_records([])
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# AC6 — Configuration drives detection; no hardcoded values
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigDrivesDetection:
    """STANDARD_DISTANCES_KM and STANDARD_POWER_DURATIONS_SECONDS drive all thresholds."""

    def test_standard_distances_exists(self):
        assert isinstance(STANDARD_DISTANCES_KM, dict)
        assert len(STANDARD_DISTANCES_KM) > 0

    def test_standard_power_durations_exists(self):
        assert isinstance(STANDARD_POWER_DURATIONS_SECONDS, dict)
        assert len(STANDARD_POWER_DURATIONS_SECONDS) > 0

    def test_standard_distances_includes_5km(self):
        assert "5km" in STANDARD_DISTANCES_KM
        assert STANDARD_DISTANCES_KM["5km"] == 5.0

    def test_standard_power_includes_20min(self):
        assert "best20Min" in STANDARD_POWER_DURATIONS_SECONDS
        assert STANDARD_POWER_DURATIONS_SECONDS["best20Min"] == 1200

    def test_speed_record_keys_match_config(self):
        """detect_speed_records result keys must be a subset of STANDARD_DISTANCES_KM."""
        run = _run("cfg1", "2026-01-01", 42.195, 14400)
        pace = 14400 / 42.195
        curve = [_pace_point(14400, pace, "cfg1", "2026-01-01", run)]
        result = detect_speed_records(curve, [run])
        record_keys = {k for k in result if k != "debug"}
        assert record_keys.issubset(set(STANDARD_DISTANCES_KM.keys()))

    def test_power_record_keys_match_config(self):
        """detect_power_records result keys must be a subset of STANDARD_POWER_DURATIONS_SECONDS."""
        run = _run("cfg2", "2026-01-02", 5.0, 1300, avg_power=280)
        curve = [
            _power_point(dur, 280.0, "cfg2", "2026-01-02", run)
            for dur in STANDARD_POWER_DURATIONS_SECONDS.values()
        ]
        result = detect_power_records(curve)
        record_keys = {k for k in result if k != "debug"}
        assert record_keys.issubset(set(STANDARD_POWER_DURATIONS_SECONDS.keys()))
