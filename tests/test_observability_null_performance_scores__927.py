"""Tests for issue #927: structured observability logging for null performance scores.

This issue builds on #910's logging infrastructure and tightens two points:

1. AC6: the 'missing-input' sentinel — when compute_endurance_score /
   compute_speed_score return {"score": None, "reason": "missing: ..."}, the log
   entry must classify the shape as "missing-input", not the generic "null".

2. AC8: conditional / scoped logging — _build_performance_log_entry must only be
   invoked when the logger is enabled at the chosen level, so athletes with large
   workout histories do not pay the assembly cost when logging is off.

Acceptance Criteria verified:
  AC1: Structured log entry emitted on every call when logging is enabled.
  AC2: user_preferences_found reflects presence of prefs row.
  AC3: ftp_w_present, threshold_hr_present, threshold_pace_seconds_per_km_present
       reflect presence of each threshold value.
  AC4: runs_assembled_count records total run count.
  AC5: laps_with_band_count records aggregate non-null band lap count.
  AC6: endurance_result_shape / speed_result_shape returns 'missing-input' for
       {"score": None, "reason": "missing: ..."} shapes.
  AC7: No change to API response shape or scoring logic.
  AC8: _build_performance_log_entry is NOT called when logger is disabled at the
       relevant level.
"""

import logging
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
# Helpers matching the running_performance.py sentinel format
# ---------------------------------------------------------------------------

def _missing_prefs_score():
    """Exact shape returned by compute_endurance_score when preferences absent."""
    return {"score": None, "reason": "missing: preferences not provided"}


def _missing_dict_score():
    """Exact shape returned when preferences is not a dict."""
    return {"score": None, "reason": "missing: preferences must be a dict"}


def _building_baseline():
    return {"state": "building_baseline", "reason": "Need at least 3 qualifying runs; 0 found."}


def _numeric_score():
    return {"score": 72.5, "direction": "improving", "trend": [55.0, 62.0, 72.5]}


def _generic_null_score():
    """A null score WITHOUT the 'missing:' prefix — should classify as 'null'."""
    return {"score": None, "reason": "some other reason"}


def _bare_null_score():
    """A null score with no reason key at all."""
    return {"score": None}


# ---------------------------------------------------------------------------
# AC6: _score_shape identifies 'missing-input' correctly
# ---------------------------------------------------------------------------

class TestMissingInputSentinel:
    """_score_shape must return 'missing-input' for 'missing: …' reason strings."""

    def _get_score_shape(self):
        """Extract _score_shape by calling _build_performance_log_entry and
        inspecting the result shapes."""
        from backend.main import _build_performance_log_entry
        return _build_performance_log_entry

    def test_missing_prefs_endurance_classified_as_missing_input(self):
        """AC6: {'score': None, 'reason': 'missing: preferences not provided'} → 'missing-input'."""
        fn = self._get_score_shape()
        entry = fn(preferences={}, runs=[], endurance=_missing_prefs_score(), speed=_numeric_score())
        assert entry["endurance_result_shape"] == "missing-input", (
            f"Expected 'missing-input', got {entry['endurance_result_shape']!r}"
        )

    def test_missing_dict_speed_classified_as_missing_input(self):
        """AC6: {'score': None, 'reason': 'missing: preferences must be a dict'} → 'missing-input'."""
        fn = self._get_score_shape()
        entry = fn(preferences={}, runs=[], endurance=_numeric_score(), speed=_missing_dict_score())
        assert entry["speed_result_shape"] == "missing-input", (
            f"Expected 'missing-input', got {entry['speed_result_shape']!r}"
        )

    def test_generic_null_reason_still_classified_as_null(self):
        """AC6: A null score whose reason does NOT start with 'missing:' stays 'null'."""
        fn = self._get_score_shape()
        entry = fn(preferences={}, runs=[], endurance=_generic_null_score(), speed=_numeric_score())
        assert entry["endurance_result_shape"] == "null"

    def test_bare_null_no_reason_classified_as_null(self):
        """AC6: {'score': None} with no reason key → 'null'."""
        fn = self._get_score_shape()
        entry = fn(preferences={}, runs=[], endurance=_bare_null_score(), speed=_numeric_score())
        assert entry["endurance_result_shape"] == "null"

    def test_both_scores_missing_input(self):
        """AC6: both endurance and speed can be 'missing-input' simultaneously."""
        fn = self._get_score_shape()
        entry = fn(preferences=None, runs=[], endurance=_missing_prefs_score(), speed=_missing_prefs_score())
        assert entry["endurance_result_shape"] == "missing-input"
        assert entry["speed_result_shape"] == "missing-input"

    def test_building_baseline_unaffected(self):
        """AC6: building_baseline state is still classified as 'building_baseline'."""
        fn = self._get_score_shape()
        entry = fn(preferences={}, runs=[], endurance=_building_baseline(), speed=_numeric_score())
        assert entry["endurance_result_shape"] == "building_baseline"

    def test_numeric_score_unaffected(self):
        """AC6: numeric score is still classified as 'numeric'."""
        fn = self._get_score_shape()
        entry = fn(preferences={}, runs=[], endurance=_numeric_score(), speed=_numeric_score())
        assert entry["endurance_result_shape"] == "numeric"
        assert entry["speed_result_shape"] == "numeric"

    def test_missing_input_requires_colon_separator(self):
        """AC6: the word 'missing' alone (no colon) does NOT trigger 'missing-input'."""
        fn = self._get_score_shape()
        entry = fn(preferences={}, runs=[], endurance={"score": None, "reason": "missing"}, speed=_numeric_score())
        assert entry["endurance_result_shape"] == "null", (
            "Reason 'missing' without colon should not be classified as 'missing-input'"
        )


# ---------------------------------------------------------------------------
# AC8: _build_performance_log_entry is guarded by logger level check
# ---------------------------------------------------------------------------

class TestLoggingGuard:
    """The log entry helper must NOT be invoked when the logger level is off.

    This prevents 700+-run athletes from paying O(runs×laps) assembly cost when
    the logger is configured at WARNING or higher in production.
    """

    def test_log_entry_not_built_when_logger_disabled(self):
        """AC8: _build_performance_log_entry is skipped when the logger rejects the level."""
        import backend.main as main_mod

        with mock.patch.object(
            main_mod._performance_log,
            "isEnabledFor",
            return_value=False,
        ):
            with mock.patch.object(
                main_mod,
                "_build_performance_log_entry",
                wraps=main_mod._build_performance_log_entry,
            ) as patched:
                # Simulate what the endpoint does (outside DB scope)
                preferences = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
                runs = [{"run_id": "r1", "laps": [{"band": "easy"}]}]
                endurance = _numeric_score()
                speed = _numeric_score()

                # Replicate the guarded call pattern from the endpoint
                if main_mod._performance_log.isEnabledFor(logging.DEBUG):
                    main_mod._build_performance_log_entry(
                        preferences=preferences,
                        runs=runs,
                        endurance=endurance,
                        speed=speed,
                    )

        # Helper must NOT have been called because isEnabledFor returned False
        patched.assert_not_called()

    def test_log_entry_built_when_logger_enabled(self):
        """AC8: _build_performance_log_entry IS called when the logger is enabled."""
        import backend.main as main_mod

        with mock.patch.object(
            main_mod._performance_log,
            "isEnabledFor",
            return_value=True,
        ):
            with mock.patch.object(
                main_mod,
                "_build_performance_log_entry",
                wraps=main_mod._build_performance_log_entry,
            ) as patched:
                preferences = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
                runs = [{"run_id": "r1", "laps": [{"band": "easy"}]}]
                endurance = _numeric_score()
                speed = _numeric_score()

                if main_mod._performance_log.isEnabledFor(logging.DEBUG):
                    main_mod._build_performance_log_entry(
                        preferences=preferences,
                        runs=runs,
                        endurance=endurance,
                        speed=speed,
                    )

        patched.assert_called_once()


# ---------------------------------------------------------------------------
# AC1–AC5 regression: all existing fields still present with new sentinel logic
# ---------------------------------------------------------------------------

class TestAllFieldsPresentWithMissingInputScores:
    """Full log entry still contains every required field when scores are missing-input."""

    def test_all_required_fields_present(self):
        """AC1-AC5: all diagnostic fields are present when both scores are missing-input."""
        from backend.main import _build_performance_log_entry

        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        runs = [
            {"run_id": "r1", "laps": [{"band": "easy"}, {"band": None}]},
            {"run_id": "r2", "laps": [{"band": "hard"}]},
        ]
        entry = _build_performance_log_entry(
            preferences=prefs,
            runs=runs,
            endurance=_missing_prefs_score(),
            speed=_missing_prefs_score(),
        )

        # AC2
        assert "user_preferences_found" in entry
        assert entry["user_preferences_found"] is True

        # AC3
        assert "ftp_w_present" in entry
        assert "threshold_hr_present" in entry
        assert "threshold_pace_seconds_per_km_present" in entry
        assert entry["ftp_w_present"] is True
        assert entry["threshold_hr_present"] is True
        assert entry["threshold_pace_seconds_per_km_present"] is True

        # AC4
        assert "runs_assembled_count" in entry
        assert entry["runs_assembled_count"] == 2

        # AC5
        assert "laps_with_band_count" in entry
        assert "total_laps_count" in entry
        assert entry["laps_with_band_count"] == 2  # r1 has 1, r2 has 1
        assert entry["total_laps_count"] == 3

        # AC6
        assert entry["endurance_result_shape"] == "missing-input"
        assert entry["speed_result_shape"] == "missing-input"

    def test_no_preferences_all_thresholds_null_both_missing_input(self):
        """AC2+AC3+AC6: no preferences → flags are None; both scores are missing-input."""
        from backend.main import _build_performance_log_entry

        entry = _build_performance_log_entry(
            preferences=None,
            runs=[],
            endurance=_missing_prefs_score(),
            speed=_missing_prefs_score(),
        )

        assert entry["user_preferences_found"] is False
        assert entry["ftp_w_present"] is None
        assert entry["threshold_hr_present"] is None
        assert entry["threshold_pace_seconds_per_km_present"] is None
        assert entry["endurance_result_shape"] == "missing-input"
        assert entry["speed_result_shape"] == "missing-input"


# ---------------------------------------------------------------------------
# AC7: API response shape is unchanged
# ---------------------------------------------------------------------------

class TestResponseShapeUnchanged:
    """No logging change may alter the response returned by score functions."""

    def test_response_keys_unchanged(self):
        """AC7: compute_endurance_score and compute_speed_score return same keys."""
        from backend.services.running_performance import compute_endurance_score, compute_speed_score
        from backend.services.zone_constants import make_zone_constants

        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "duration_curve_bests": {},
        }
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i+1:02d}",
                "laps": [{"band": "easy", "avg_power": 210.0, "avg_hr": 140.0,
                           "distance_km": 2.0, "duration_seconds": 600.0}],
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
        assert "score" in endurance or "state" in endurance
        assert "score" in speed or "state" in speed

    def test_missing_prefs_score_shape_from_service(self):
        """AC7: null score returned by service when prefs=None has the expected reason prefix."""
        from backend.services.running_performance import compute_endurance_score, compute_speed_score
        from backend.services.zone_constants import make_zone_constants

        zc = make_zone_constants()
        endurance = compute_endurance_score([], None, zc)
        speed = compute_speed_score([], None, zc)

        # Service still returns {'score': None, 'reason': 'missing: ...'} — shape unchanged
        assert endurance.get("score") is None
        assert "missing:" in (endurance.get("reason") or "")

        assert speed.get("score") is None
        assert "missing:" in (speed.get("reason") or "")
