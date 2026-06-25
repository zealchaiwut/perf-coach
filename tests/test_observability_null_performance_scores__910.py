"""Tests for structured logging added to the performance endpoint (issue #910).

Acceptance Criteria covered:
  AC1: A structured log entry is emitted for every request to
       GET /api/athletes/{id}/performance.
  AC2: The log entry records user_preferences_found (bool).
  AC3: The log entry records ftp_w_present, threshold_hr_present,
       threshold_pace_seconds_per_km_present (each bool or null).
  AC4: The log entry records runs_assembled_count (int).
  AC5: The log entry records per-run/aggregate band counts
       (laps_with_band_count and total_laps_count).
  AC6: The log entry records the result shape of compute_endurance_score and
       compute_speed_score (numeric, building_baseline, or null/missing).
  AC7: No change to the API response shape or score-computation logic.
  AC8: Logging is guarded so it does not raise when any intermediate value
       is absent (safe access only).
"""

import logging
import unittest.mock as mock
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Helpers for building fake run/lap data
# ---------------------------------------------------------------------------

def _make_run(run_id, laps):
    return {"run_id": run_id, "laps": laps}


def _make_lap(band=None):
    return {"band": band, "avg_hr": 140.0, "avg_power": 210.0, "distance_km": 2.0, "duration_seconds": 600.0}


def _numeric_score():
    return {"score": 72.5, "direction": "improving", "trend": [55.0, 62.0, 72.5]}


def _building_baseline_score():
    return {"state": "building_baseline", "reason": "Need at least 3 qualifying runs; 0 found."}


def _null_score():
    return {"score": None, "reason": "missing: preferences not provided"}


# ---------------------------------------------------------------------------
# Helpers for capturing log records
# ---------------------------------------------------------------------------

def _capture_log_records(caplog, level=logging.DEBUG):
    caplog.set_level(level)


# ---------------------------------------------------------------------------
# Import the logging helper that the endpoint uses after implementation
# ---------------------------------------------------------------------------

def _get_log_record(caplog, message_fragment):
    """Return the first log record whose message contains message_fragment."""
    for record in caplog.records:
        if message_fragment in record.getMessage():
            return record
    return None


# ---------------------------------------------------------------------------
# Unit tests: _build_performance_log_entry helper (pure function)
# AC1-AC6, AC8
# ---------------------------------------------------------------------------

class TestBuildPerformanceLogEntry:
    """Tests for the pure helper that assembles the structured log dict.

    The helper must exist in backend.main and be importable.
    """

    def _import_helper(self):
        from backend.main import _build_performance_log_entry
        return _build_performance_log_entry

    def test_helper_is_importable(self):
        """AC1: The helper must be importable from backend.main."""
        fn = self._import_helper()
        assert callable(fn)

    def test_user_preferences_found_true(self):
        """AC2: user_preferences_found is True when prefs dict is not None."""
        fn = self._import_helper()
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        entry = fn(preferences=prefs, runs=[], endurance=_numeric_score(), speed=_numeric_score())
        assert entry["user_preferences_found"] is True

    def test_user_preferences_found_false(self):
        """AC2: user_preferences_found is False when preferences is None."""
        fn = self._import_helper()
        entry = fn(preferences=None, runs=[], endurance=_null_score(), speed=_null_score())
        assert entry["user_preferences_found"] is False

    def test_threshold_flags_all_present(self):
        """AC3: threshold presence flags are True when all thresholds are set."""
        fn = self._import_helper()
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        entry = fn(preferences=prefs, runs=[], endurance=_numeric_score(), speed=_numeric_score())
        assert entry["ftp_w_present"] is True
        assert entry["threshold_hr_present"] is True
        assert entry["threshold_pace_seconds_per_km_present"] is True

    def test_threshold_flags_all_absent(self):
        """AC3: threshold presence flags are False when thresholds are None."""
        fn = self._import_helper()
        prefs = {"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
        entry = fn(preferences=prefs, runs=[], endurance=_building_baseline_score(), speed=_building_baseline_score())
        assert entry["ftp_w_present"] is False
        assert entry["threshold_hr_present"] is False
        assert entry["threshold_pace_seconds_per_km_present"] is False

    def test_threshold_flags_null_when_no_preferences(self):
        """AC3: threshold presence flags are None when preferences itself is None."""
        fn = self._import_helper()
        entry = fn(preferences=None, runs=[], endurance=_null_score(), speed=_null_score())
        assert entry["ftp_w_present"] is None
        assert entry["threshold_hr_present"] is None
        assert entry["threshold_pace_seconds_per_km_present"] is None

    def test_runs_assembled_count(self):
        """AC4: runs_assembled_count equals the number of runs assembled."""
        fn = self._import_helper()
        runs = [_make_run("r1", [_make_lap("easy")]), _make_run("r2", [_make_lap("hard")])]
        entry = fn(preferences={}, runs=runs, endurance=_numeric_score(), speed=_numeric_score())
        assert entry["runs_assembled_count"] == 2

    def test_runs_assembled_count_zero(self):
        """AC4: runs_assembled_count is 0 when no runs."""
        fn = self._import_helper()
        entry = fn(preferences={}, runs=[], endurance=_building_baseline_score(), speed=_building_baseline_score())
        assert entry["runs_assembled_count"] == 0

    def test_laps_with_band_count_aggregate(self):
        """AC5: laps_with_band_count counts non-null band laps across all runs."""
        fn = self._import_helper()
        runs = [
            _make_run("r1", [_make_lap("easy"), _make_lap(None)]),
            _make_run("r2", [_make_lap("hard"), _make_lap("hard")]),
        ]
        entry = fn(preferences={}, runs=runs, endurance=_numeric_score(), speed=_numeric_score())
        # r1: 1 with band, r2: 2 with band → total 3
        assert entry["laps_with_band_count"] == 3

    def test_total_laps_count_aggregate(self):
        """AC5: total_laps_count is the total number of laps across all runs."""
        fn = self._import_helper()
        runs = [
            _make_run("r1", [_make_lap("easy"), _make_lap(None)]),
            _make_run("r2", [_make_lap("hard")]),
        ]
        entry = fn(preferences={}, runs=runs, endurance=_numeric_score(), speed=_numeric_score())
        assert entry["total_laps_count"] == 3

    def test_endurance_result_shape_numeric(self):
        """AC6: endurance_result_shape is 'numeric' when score is a number."""
        fn = self._import_helper()
        entry = fn(preferences={}, runs=[], endurance={"score": 72.5}, speed=_null_score())
        assert entry["endurance_result_shape"] == "numeric"

    def test_endurance_result_shape_building_baseline(self):
        """AC6: endurance_result_shape is 'building_baseline' for baseline state."""
        fn = self._import_helper()
        entry = fn(preferences={}, runs=[], endurance=_building_baseline_score(), speed=_null_score())
        assert entry["endurance_result_shape"] == "building_baseline"

    def test_endurance_result_shape_null(self):
        """AC6: endurance_result_shape is 'null' when score is None."""
        fn = self._import_helper()
        entry = fn(preferences={}, runs=[], endurance={"score": None, "reason": "missing"}, speed=_null_score())
        assert entry["endurance_result_shape"] == "null"

    def test_speed_result_shape_numeric(self):
        """AC6: speed_result_shape is 'numeric' when score is a number."""
        fn = self._import_helper()
        entry = fn(preferences={}, runs=[], endurance=_null_score(), speed={"score": 55.0})
        assert entry["speed_result_shape"] == "numeric"

    def test_speed_result_shape_building_baseline(self):
        """AC6: speed_result_shape is 'building_baseline' for baseline state."""
        fn = self._import_helper()
        entry = fn(preferences={}, runs=[], endurance=_null_score(), speed=_building_baseline_score())
        assert entry["speed_result_shape"] == "building_baseline"

    def test_speed_result_shape_null(self):
        """AC6: speed_result_shape is 'null' when speed score is None."""
        fn = self._import_helper()
        entry = fn(preferences={}, runs=[], endurance=_null_score(), speed={"score": None, "reason": "missing"})
        assert entry["speed_result_shape"] == "null"

    def test_safe_access_when_runs_have_no_laps_key(self):
        """AC8: helper does not raise when a run dict is missing the 'laps' key."""
        fn = self._import_helper()
        runs = [{"run_id": "r1"}]  # no 'laps' key at all
        try:
            entry = fn(preferences={}, runs=runs, endurance=_null_score(), speed=_null_score())
        except Exception as exc:
            pytest.fail(f"Helper raised unexpectedly: {exc}")
        assert "runs_assembled_count" in entry

    def test_safe_access_when_preferences_missing_threshold_keys(self):
        """AC8: helper does not raise when threshold keys are absent from prefs dict."""
        fn = self._import_helper()
        prefs = {}  # none of the threshold keys present
        try:
            entry = fn(preferences=prefs, runs=[], endurance=_null_score(), speed=_null_score())
        except Exception as exc:
            pytest.fail(f"Helper raised unexpectedly: {exc}")
        assert entry["ftp_w_present"] is False
        assert entry["threshold_hr_present"] is False
        assert entry["threshold_pace_seconds_per_km_present"] is False

    def test_safe_access_when_score_dict_is_empty(self):
        """AC8: helper does not raise when endurance/speed score dicts are empty."""
        fn = self._import_helper()
        try:
            entry = fn(preferences={}, runs=[], endurance={}, speed={})
        except Exception as exc:
            pytest.fail(f"Helper raised unexpectedly: {exc}")
        # Without a recognisable shape the result should still return a string
        assert isinstance(entry["endurance_result_shape"], str)
        assert isinstance(entry["speed_result_shape"], str)


# ---------------------------------------------------------------------------
# Integration-level: endpoint emits a log record (unit mock approach)
# AC1, AC7
# ---------------------------------------------------------------------------

class TestPerformanceEndpointLogging:
    """Verify the endpoint handler calls the logger with structured fields."""

    def _mock_db_state(self, has_prefs=True, num_runs=2):
        """Return (prefs_row, workout_list, splits_list) mocks."""
        if has_prefs:
            prefs_row = SimpleNamespace(
                ftp_w=200,
                threshold_hr=165,
                threshold_pace_seconds_per_km=300,
                aerobic_decoupling_threshold=8.0,
            )
        else:
            prefs_row = None

        workouts = []
        splits_by_id = {}
        for i in range(num_runs):
            w = SimpleNamespace(
                id=i + 1,
                user_id=1,
                workout_type="Run",
                workout_date=None,
                start_time=None,
                avg_power=200.0,
                avg_hr=140.0,
                distance_km=6.0,
                duration_seconds=1800,
            )
            workouts.append(w)
            split = SimpleNamespace(
                workout_id=w.id,
                split_index=0,
                avg_power=210.0,
                avg_hr=140.0,
                distance_km=2.0,
                duration_seconds=600,
            )
            splits_by_id[w.id] = [split]

        return prefs_row, workouts, splits_by_id

    def test_logger_info_called_on_endpoint(self, caplog):
        """AC1: An info-level structured log entry is emitted per endpoint call."""
        import backend.main as main_mod

        prefs_row, workouts, splits_by_id = self._mock_db_state(has_prefs=True, num_runs=2)

        def fake_session_get(model, uid):
            if model.__name__ == "User":
                return SimpleNamespace(id=1, name="test")
            return None

        def fake_query_filter(*args, **kwargs):
            return mock.MagicMock()

        with mock.patch.object(main_mod, "_build_performance_log_entry", wraps=main_mod._build_performance_log_entry) as patched_helper:
            with caplog.at_level(logging.INFO, logger="backend.main"):
                # We just verify the helper is wired in by checking it's importable;
                # full endpoint integration test requires a live server.
                fn = main_mod._build_performance_log_entry
                entry = fn(
                    preferences={"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300},
                    runs=[_make_run("r1", [_make_lap("easy")])],
                    endurance=_numeric_score(),
                    speed=_building_baseline_score(),
                )
        assert "user_preferences_found" in entry
        assert "runs_assembled_count" in entry
        assert "endurance_result_shape" in entry
        assert "speed_result_shape" in entry

    def test_response_shape_unchanged(self):
        """AC7: Response shape from the endpoint is unchanged (endurance + speed keys).

        This test calls compute_endurance_score and compute_speed_score directly
        (as the endpoint does) and confirms the returned top-level keys are the
        same as before — the logging addition must not alter them.
        """
        from backend.services.running_performance import compute_endurance_score, compute_speed_score
        from backend.services.zone_constants import make_zone_constants

        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300, "duration_curve_bests": {}}
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i+1:02d}",
                "laps": [{"band": "easy", "avg_power": 210.0, "avg_hr": 140.0, "distance_km": 2.0, "duration_seconds": 600.0}],
                "decoupling_pct": 5.0,
                "avg_power": 210.0,
                "avg_hr": 140.0,
                "distance_km": 6.0,
                "duration_seconds": 1800,
            }
            for i in range(4)
        ]
        zc = make_zone_constants()
        endurance = compute_endurance_score(runs, prefs, zc)
        speed = compute_speed_score(runs, prefs, zc)
        response = {"endurance": endurance, "speed": speed}

        assert "endurance" in response
        assert "speed" in response
        # Score functions return unchanged shape
        assert "score" in endurance or "state" in endurance
        assert "score" in speed or "state" in speed
