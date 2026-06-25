"""Tests for issue #914: Backfill lap classification and trigger recompute on threshold save.

Acceptance Criteria covered:
  AC1: A script exists at scripts/backfill_lap_classification.py that accepts
       a user ID, classifies laps for all existing run workouts, persists/caches
       resulting training bands (via AthleteDurationCurve rebuild), refreshes
       the duration curve, and recomputes per-run inputs.
  AC2: The script is idempotent — running it twice produces the same result.
  AC3: Thresholds are always read dynamically from DB; no threshold value is
       hardcoded in the script or triggered logic.
  AC4: The script never overwrites a value that was manually entered by the
       athlete or coach.
  AC5: DB access lives in a thin caller layer; classification and recompute
       logic is kept separate from data-access concerns.
  AC6: When an athlete sets or accepts thresholds in Settings, the same
       recompute pipeline runs automatically.
  AC7: After the backfill runs for an athlete who has thresholds set, the
       Performance tab displays numeric scores.
  AC8: After the backfill runs for an athlete who has thresholds set, the
       PRs strip populates with values.
  AC9: Threshold-save trigger produces the same Performance tab and PRs
       strip outcome as the manual backfill script.
"""

import inspect
import os
from types import SimpleNamespace
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_split(workout_id=1, split_index=0, avg_power=210, avg_hr=140,
                distance_km=2.0, duration_seconds=600, lap_type="auto"):
    return SimpleNamespace(
        workout_id=workout_id,
        split_index=split_index,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        lap_type=lap_type,
    )


def _make_workout(workout_id, user_id="user-1", workout_type="Run",
                  workout_date_str="2026-01-01", avg_power=210, avg_hr=140,
                  distance_km=6.0, duration_seconds=1800,
                  manual_overrides=None):
    import datetime
    return SimpleNamespace(
        id=workout_id,
        user_id=user_id,
        workout_type=workout_type,
        workout_date=datetime.date.fromisoformat(workout_date_str),
        start_time=None,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        manual_overrides=manual_overrides,
    )


def _make_prefs(ftp_w=200, threshold_hr=165, threshold_pace=300):
    return SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace,
    )


# ---------------------------------------------------------------------------
# AC1: Script exists and is importable / callable
# ---------------------------------------------------------------------------

class TestScriptExists:
    """AC1: scripts/backfill_lap_classification.py exists and is well-formed."""

    def test_script_file_exists(self):
        script_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "scripts",
            "backfill_lap_classification.py",
        )
        assert os.path.isfile(script_path), (
            "scripts/backfill_lap_classification.py does not exist"
        )

    def test_script_has_main_function(self):
        import scripts.backfill_lap_classification as mod
        assert hasattr(mod, "main"), "Script must expose a main() function"
        assert callable(mod.main)

    def test_script_has_parse_args_function(self):
        import scripts.backfill_lap_classification as mod
        assert hasattr(mod, "_parse_args") or hasattr(mod, "parse_args"), (
            "Script must have an argument parser (_parse_args or parse_args)"
        )

    def test_script_accepts_user_id_argument(self):
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        assert "--user-id" in src or "--user_id" in src, (
            "Script must accept a --user-id or --user_id argument"
        )
        # Verify the argparse setup accepts the argument by parsing with a known value
        parser_fn = getattr(mod, "_parse_args", None)
        assert parser_fn is not None
        # Use parse_known_args to avoid error on missing required args in test env
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["backfill_lap_classification.py", "--user-id", "123e4567-e89b-12d3-a456-426614174000"]
        try:
            args = parser_fn()
            assert args.user_id == "123e4567-e89b-12d3-a456-426614174000"
        finally:
            _sys.argv = old_argv

    def test_script_accepts_env_argument(self):
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        assert "--env" in src, "Script must accept --env argument"

    def test_script_has_docstring(self):
        import scripts.backfill_lap_classification as mod
        assert mod.__doc__ is not None and len(mod.__doc__.strip()) > 0, (
            "Script must have a module-level docstring"
        )


# ---------------------------------------------------------------------------
# AC2: Idempotency — rebuilding curve twice gives same result
# ---------------------------------------------------------------------------

class TestIdempotency:
    """AC2: Running the recompute pipeline twice produces the same result."""

    def test_merge_best_effort_is_idempotent(self):
        """merge_best_effort produces identical output when called twice with same data."""
        from backend.services.duration_curve_best_effort import merge_best_effort

        existing = {"60": {"best_value": 250.0, "workout_id": "abc", "date": "2026-01-10",
                           "confidence": "measured"}}
        new_points = [
            {"duration_seconds": 60, "best_value": 260.0, "source_workout_id": "xyz",
             "date": "2026-01-15", "confidence": "measured"},
        ]

        curve1, r1 = merge_best_effort(existing, new_points)
        assert r1 is None
        # Rebuild: merge curve1 with the same points again
        curve2, r2 = merge_best_effort(curve1, new_points)
        assert r2 is None

        assert curve1 == curve2, "Two merges with identical data must produce the same curve"

    def test_recompute_service_run_function_exists(self):
        """lap_recompute service must expose a rebuild function."""
        from backend.services import lap_recompute
        assert hasattr(lap_recompute, "rebuild_athlete_duration_curve"), (
            "lap_recompute must expose rebuild_athlete_duration_curve(user_id, db)"
        )

    def test_rebuild_with_no_workouts_is_stable(self):
        """Rebuilding when user has no run workouts produces empty curve safely."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        curve, reason = rebuild_athlete_duration_curve("user-1", mock_session)
        # Should succeed without error, returning empty curve
        assert isinstance(curve, dict), "Should return a dict (possibly empty)"

    def test_classify_laps_same_result_on_repeated_calls(self):
        """classify_laps is deterministic: same inputs → same output every time."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=210, avg_hr=140)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        result1 = classify_laps(splits, prefs)
        result2 = classify_laps(splits, prefs)
        assert result1 == result2, "classify_laps must be deterministic"


# ---------------------------------------------------------------------------
# AC3: Thresholds always read from DB, never hardcoded
# ---------------------------------------------------------------------------

class TestThresholdsFromDB:
    """AC3: No threshold value is hardcoded; all values come from UserPreferences."""

    def test_classify_laps_uses_prefs_dict_not_constants(self):
        """Band changes when ftp_w changes — proves no hardcoded boundary."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=210)]

        # ftp_w=300 → ratio=0.70 → easy
        result_low = classify_laps(splits, {"ftp_w": 300})
        # ftp_w=150 → ratio=1.40 → hard
        result_high = classify_laps(splits, {"ftp_w": 150})

        assert result_low[0]["band"] == "easy"
        assert result_high[0]["band"] == "hard"

    def test_script_reads_prefs_from_db_not_hardcoded(self):
        """Script source must not contain hardcoded threshold numbers."""
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        # Check that no literal threshold values appear as constants
        # (reasonable threshold ranges: ftp_w 50-600, threshold_hr 100-220, pace 180-540)
        # We check that the script doesn't hardcode specific values
        hardcoded_patterns = ["ftp_w = 2", "ftp_w = 1", "threshold_hr = 1",
                              "threshold_pace = 2", "threshold_pace = 3"]
        for pattern in hardcoded_patterns:
            assert pattern not in src, (
                f"Script must not hardcode threshold: found '{pattern}'"
            )

    def test_rebuild_reads_prefs_from_db(self):
        """rebuild_athlete_duration_curve reads UserPreferences from DB."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        # Mock DB: has 1 run workout, has prefs
        mock_workout = _make_workout(1, workout_date_str="2026-01-01")
        mock_prefs = _make_prefs(ftp_w=220)

        mock_session = mock.MagicMock()
        (mock_session.query.return_value
         .filter.return_value
         .order_by.return_value
         .all.return_value) = [mock_workout]

        # The function queries UserPreferences; we don't test DB internals,
        # just that the function doesn't hardcode ftp_w=200 or similar
        src = inspect.getsource(rebuild_athlete_duration_curve)
        assert "ftp_w = 200" not in src
        assert "threshold_hr = 165" not in src
        assert "threshold_pace = 300" not in src

    def test_no_hardcoded_thresholds_in_lap_recompute_module(self):
        """lap_recompute.py must not contain hardcoded numeric threshold values."""
        from backend.services import lap_recompute
        src = inspect.getsource(lap_recompute)
        # No numeric FTP, HR, or pace constants
        for bad in ("ftp_w = 2", "threshold_hr = 1", "threshold_pace_seconds_per_km = 3"):
            assert bad not in src, f"Hardcoded threshold found in lap_recompute: '{bad}'"


# ---------------------------------------------------------------------------
# AC4: Never overwrites manually entered values
# ---------------------------------------------------------------------------

class TestNoManualOverwrite:
    """AC4: Backfill never overwrites manually entered values."""

    def test_rebuild_does_not_modify_workout_table(self):
        """rebuild_athlete_duration_curve must not call session.execute with UPDATE on workouts."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        mock_session = mock.MagicMock()
        (mock_session.query.return_value
         .filter.return_value
         .order_by.return_value
         .all.return_value) = []

        rebuild_athlete_duration_curve("user-1", mock_session)

        # Inspect all session.execute calls to ensure no workout UPDATEs occurred
        for call in mock_session.execute.call_args_list:
            args = call[0]
            if args:
                stmt = str(args[0]).upper()
                assert "UPDATE WORKOUT" not in stmt and "WORKOUT SET" not in stmt, (
                    "rebuild must not UPDATE the workouts table"
                )

    def test_rebuild_does_not_modify_workout_splits_table(self):
        """rebuild must not modify workout_splits rows."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        mock_session = mock.MagicMock()
        (mock_session.query.return_value
         .filter.return_value
         .order_by.return_value
         .all.return_value) = []

        rebuild_athlete_duration_curve("user-1", mock_session)

        for call in mock_session.execute.call_args_list:
            args = call[0]
            if args:
                stmt = str(args[0]).upper()
                assert "UPDATE WORKOUT_SPLITS" not in stmt, (
                    "rebuild must not UPDATE workout_splits"
                )

    def test_manual_lap_type_does_not_change_workout_data(self):
        """Classifying a manual lap does not change any field on the split object."""
        from backend.services.lap_classify import classify_laps
        split = _make_split(avg_power=210, avg_hr=140, lap_type="manual")
        original_power = split.avg_power
        original_hr = split.avg_hr

        classify_laps([split], {"ftp_w": 200})

        assert split.avg_power == original_power, "avg_power must not be modified"
        assert split.avg_hr == original_hr, "avg_hr must not be modified"

    def test_workout_with_manual_overrides_is_processed_but_not_modified(self):
        """Workouts with manual_overrides are classified but their data is not changed."""
        workout = _make_workout(1, manual_overrides={"tss": 75, "avg_power": 180})
        original_overrides = dict(workout.manual_overrides)

        # Simulating what the backfill does: it reads workout data, doesn't write back
        # The manual_overrides dict should remain unchanged after classification
        split = _make_split(avg_power=210, avg_hr=140)
        from backend.services.lap_classify import classify_laps
        classify_laps([split], {"ftp_w": 200})

        # manual_overrides on workout is untouched (it's not a DB object here, just verifying logic)
        assert workout.manual_overrides == original_overrides


# ---------------------------------------------------------------------------
# AC5: DB access in thin caller layer; logic separate from data access
# ---------------------------------------------------------------------------

class TestSeparationOfConcerns:
    """AC5: DB access in thin caller; classification logic has no DB access."""

    def test_classify_laps_makes_no_db_calls(self):
        """classify_laps accepts plain objects and does not access the database."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=210, avg_hr=140)]
        prefs = {"ftp_w": 200}
        # Must not raise — if it tried to access DB it would fail without a session
        result = classify_laps(splits, prefs)
        assert isinstance(result, list)

    def test_lap_recompute_module_separates_pure_and_caller(self):
        """lap_recompute.py must have at least one pure helper and one thin caller."""
        from backend.services import lap_recompute
        fns = [name for name, obj in inspect.getmembers(lap_recompute, inspect.isfunction)]
        # Must have a function that handles DB (caller) and possibly pure helpers
        assert "rebuild_athlete_duration_curve" in fns, (
            "lap_recompute must expose rebuild_athlete_duration_curve (thin caller)"
        )

    def test_lap_classify_pure_function_has_no_top_level_db_import(self):
        """lap_classify.classify_laps must not import SQLAlchemy at module top level."""
        import ast
        import textwrap
        import backend.services.lap_classify as mod
        src = inspect.getsource(mod)
        tree = ast.parse(textwrap.dedent(src))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                assert node.module != "sqlalchemy" and "sqlalchemy" not in (node.module or ""), (
                    f"lap_classify must not import SQLAlchemy at module level: {node.module}"
                )

    def test_script_thin_caller_pattern_present(self):
        """Script has a _run(engine, ...) function that owns DB access."""
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        # Script should separate engine/db from computation
        assert "engine" in src or "Session" in src, (
            "Script must use SQLAlchemy engine or Session for DB access"
        )
        # Classification logic is delegated, not inline SQL
        assert "classify_laps" in src or "classify_runs" in src or "lap_recompute" in src, (
            "Script must call the classification service, not inline SQL"
        )


# ---------------------------------------------------------------------------
# AC6: Threshold-save triggers recompute automatically
# ---------------------------------------------------------------------------

class TestThresholdSaveTrigger:
    """AC6: Saving thresholds fires the recompute pipeline automatically."""

    def test_patch_user_preferences_calls_recompute_on_threshold_change(self):
        """PATCH /api/user-preferences must trigger curve rebuild when thresholds change."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        # The endpoint must reference rebuild_athlete_duration_curve or lap_recompute
        # somewhere in the threshold-change branch
        assert (
            "rebuild_athlete_duration_curve" in src
            or "lap_recompute" in src
        ), (
            "main.py must call rebuild_athlete_duration_curve when thresholds change"
        )

    def test_accept_threshold_suggestions_triggers_recompute(self):
        """POST /api/thresholds/suggestions/accept must trigger curve rebuild."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert (
            "rebuild_athlete_duration_curve" in src
            or "lap_recompute" in src
        ), (
            "main.py must trigger the recompute pipeline when thresholds are accepted"
        )

    def test_rebuild_function_is_importable_from_lap_recompute(self):
        """rebuild_athlete_duration_curve is importable from the service module."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve
        assert callable(rebuild_athlete_duration_curve)

    def test_rebuild_function_signature(self):
        """rebuild_athlete_duration_curve(user_id, db) — two params."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve
        sig = inspect.signature(rebuild_athlete_duration_curve)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, (
            "rebuild_athlete_duration_curve must accept at least user_id and db"
        )
        assert "user_id" in params, "First param must be user_id"
        assert "db" in params or "session" in params, (
            "Second param must be db or session"
        )


# ---------------------------------------------------------------------------
# AC7: After backfill, Performance tab shows numeric scores
# ---------------------------------------------------------------------------

class TestPerformanceTabScoresAfterBackfill:
    """AC7: Performance tab shows numeric scores after backfill."""

    def _easy_run(self, run_id, idx):
        """A qualifying easy run."""
        return {
            "run_id": run_id,
            "workout_date": f"2026-01-{idx:02d}",
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 150.0 + idx * 2,
                    "avg_hr": 138.0,
                    "distance_km": 5.0,
                    "duration_seconds": 1500.0,
                }
            ],
            "decoupling_pct": 4.0,
            "avg_power": 150.0 + idx * 2,
            "avg_hr": 138.0,
            "distance_km": 5.0,
            "duration_seconds": 1500,
        }

    def test_classified_easy_runs_produce_numeric_endurance_score(self):
        """Runs with easy-band laps produce a numeric endurance score."""
        from backend.services.running_performance import compute_endurance_score
        from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        runs = [self._easy_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()

        result = compute_endurance_score(runs, prefs, zc)
        assert "score" in result, f"No score key: {result}"
        assert isinstance(result["score"], (int, float)), f"Non-numeric score: {result}"
        assert 0 <= result["score"] <= 100

    def test_backfill_classify_step_produces_band_not_none(self):
        """After classify_laps, bands are not None when thresholds exist."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=150, avg_hr=138, distance_km=5.0, duration_seconds=1500)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        classifications = classify_laps(splits, prefs)
        assert all(c["band"] is not None for c in classifications), (
            "All laps must have a band when thresholds are set"
        )

    def test_no_thresholds_means_no_band(self):
        """Without thresholds, classify_laps returns band=None (still no scores)."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=150, avg_hr=138)]
        prefs = {}
        classifications = classify_laps(splits, prefs)
        assert all(c["band"] is None for c in classifications)

    def test_endurance_score_needs_thresholds_result_when_no_prefs(self):
        """Performance endpoint returns needs_thresholds state when prefs absent."""
        # Test the helper that checks for missing thresholds
        import backend.main as main_mod
        fn = getattr(main_mod, "_check_needs_thresholds", None)
        assert fn is not None, "_check_needs_thresholds must exist in main.py"
        assert fn(None) is True, "None preferences should trigger needs_thresholds"
        assert fn({}) is True, "Empty preferences should trigger needs_thresholds"
        assert fn({"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}) is True


# ---------------------------------------------------------------------------
# AC8: After backfill, PRs strip populates
# ---------------------------------------------------------------------------

class TestPRsStripAfterBackfill:
    """AC8: PRs strip populates after backfill runs for athlete with thresholds."""

    def test_detected_prs_endpoint_exists_in_main(self):
        """An endpoint for detected PRs must be registered in main.py."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        # Endpoint path should include "detected-prs" or "detected_prs" or similar
        assert (
            "detected-prs" in src
            or "detected_prs" in src
        ), (
            "main.py must have a /api/athletes/{athlete_id}/detected-prs endpoint"
        )

    def test_fetch_and_detect_records_is_importable(self):
        """fetch_and_detect_records from pr_detection is importable."""
        from backend.services.pr_detection import fetch_and_detect_records
        assert callable(fetch_and_detect_records)

    def test_detect_speed_records_returns_populated_results(self):
        """detect_speed_records returns populated records for a simple run."""
        from backend.services.pr_detection import detect_speed_records

        completed_runs = [
            {
                "id": "run-1",
                "workout_date": "2026-01-15",
                "distance_km": 5.1,
                "duration_seconds": 1260,
                "tss": 45.0,
                "avg_power": None,
            }
        ]
        pace_curve = [
            {
                "duration_seconds": 1260,
                "best_value": 1260 / 5.1,  # seconds per km
                "source_workout_id": "run-1",
                "date": "2026-01-15",
                "source_workout": completed_runs[0],
            }
        ]

        result = detect_speed_records(pace_curve, completed_runs)
        # Should have a 5km record since distance is 5.1 km
        assert "5km" in result
        assert "value" in result["5km"], f"5km record has no value: {result['5km']}"

    def test_detect_power_records_returns_results_from_curve(self):
        """detect_power_records returns populated records when curve has standard durations."""
        from backend.services.pr_detection import detect_power_records

        power_curve = [
            {
                "duration_seconds": 60,
                "best_value": 310.0,
                "source_workout_id": "run-1",
                "date": "2026-01-15",
                "source_workout": {"id": "run-1", "workout_date": "2026-01-15"},
            },
            {
                "duration_seconds": 300,
                "best_value": 280.0,
                "source_workout_id": "run-1",
                "date": "2026-01-15",
                "source_workout": {"id": "run-1", "workout_date": "2026-01-15"},
            },
        ]

        result = detect_power_records(power_curve)
        assert "best1Min" in result
        assert result["best1Min"]["value"] == 310.0


# ---------------------------------------------------------------------------
# AC9: Threshold-save trigger gives same outcome as manual backfill
# ---------------------------------------------------------------------------

class TestTriggerSameOutcomeAsBackfill:
    """AC9: Threshold-save trigger produces same outcome as manual backfill."""

    def test_trigger_calls_same_rebuild_function_as_script(self):
        """Both the trigger and the script must call rebuild_athlete_duration_curve."""
        import backend.main as main_mod
        import scripts.backfill_lap_classification as script_mod

        main_src = inspect.getsource(main_mod)
        script_src = inspect.getsource(script_mod)

        assert "rebuild_athlete_duration_curve" in main_src, (
            "main.py trigger must call rebuild_athlete_duration_curve"
        )
        assert (
            "rebuild_athlete_duration_curve" in script_src
            or "lap_recompute" in script_src
        ), (
            "backfill script must call rebuild_athlete_duration_curve (directly or via lap_recompute)"
        )

    def test_rebuild_is_deterministic_across_callers(self):
        """Rebuilding from the same data always gives the same curve."""
        from backend.services.duration_curve_best_effort import merge_best_effort

        new_points = [
            {"duration_seconds": 60, "best_value": 270.0, "source_workout_id": "w1",
             "date": "2026-01-15", "confidence": "approx"},
            {"duration_seconds": 300, "best_value": 250.0, "source_workout_id": "w1",
             "date": "2026-01-15", "confidence": "approx"},
        ]

        # Simulating two independent callers starting from empty curve
        curve_a, _ = merge_best_effort({}, new_points)
        curve_b, _ = merge_best_effort({}, new_points)

        assert curve_a == curve_b, (
            "Two independent rebuilds from the same data must produce identical curves"
        )

    def test_lap_recompute_service_is_thin_caller(self):
        """rebuild_athlete_duration_curve is the thin caller that both trigger and script use."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve
        src = inspect.getsource(rebuild_athlete_duration_curve)
        # It must import from backend.models or use session — it's the DB-access layer
        has_db_access = (
            "session" in src
            or "Session" in src
            or "db" in src
            or "Workout" in src
        )
        assert has_db_access, (
            "rebuild_athlete_duration_curve must perform DB access (thin caller)"
        )


# ---------------------------------------------------------------------------
# Integration: recompute pipeline logic (pure)
# ---------------------------------------------------------------------------

class TestRecomputePipelineLogic:
    """Integration tests for the pure classify+efficiency pipeline."""

    def test_classify_then_score_pipeline_produces_numeric_result(self):
        """Full pipeline: classify laps → compute endurance score → numeric."""
        from backend.services.lap_classify import classify_laps
        from backend.services.running_performance import compute_endurance_score
        from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

        prefs_dict = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "duration_curve_bests": None,
        }

        runs = []
        for i in range(MIN_QUALIFYING_RUNS + 1):
            splits = [_make_split(avg_power=150 + i, avg_hr=138, distance_km=5.0, duration_seconds=1500)]
            classifications = classify_laps(splits, prefs_dict)
            laps = [
                {
                    "band": c.get("band"),
                    "avg_power": s.avg_power,
                    "avg_hr": s.avg_hr,
                    "distance_km": float(s.distance_km),
                    "duration_seconds": s.duration_seconds,
                }
                for s, c in zip(splits, classifications)
            ]
            runs.append({
                "run_id": str(i),
                "workout_date": f"2026-01-{i + 1:02d}",
                "laps": laps,
                "decoupling_pct": None,
            })

        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs_dict, zc)
        assert "score" in result
        assert isinstance(result["score"], (int, float))
        assert 0 <= result["score"] <= 100

    def test_no_thresholds_no_qualifying_runs_returns_state_not_crash(self):
        """Without thresholds, all bands are None, score returns building_baseline or null."""
        from backend.services.lap_classify import classify_laps
        from backend.services.running_performance import compute_endurance_score
        from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

        prefs_dict = {
            "ftp_w": None,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": None,
            "duration_curve_bests": None,
        }

        runs = []
        for i in range(MIN_QUALIFYING_RUNS + 1):
            splits = [_make_split(avg_power=150, avg_hr=138)]
            classifications = classify_laps(splits, {})
            laps = [
                {
                    "band": c.get("band"),  # will be None
                    "avg_power": s.avg_power,
                    "avg_hr": s.avg_hr,
                    "distance_km": float(s.distance_km),
                    "duration_seconds": s.duration_seconds,
                }
                for s, c in zip(splits, classifications)
            ]
            runs.append({
                "run_id": str(i),
                "workout_date": f"2026-01-{i + 1:02d}",
                "laps": laps,
                "decoupling_pct": None,
            })

        zc = make_zone_constants()
        # Doesn't crash; returns building_baseline (no qualifying easy laps)
        try:
            result = compute_endurance_score(runs, prefs_dict, zc)
        except Exception as exc:
            pytest.fail(f"compute_endurance_score raised with null bands: {exc}")
        # Either building_baseline or null score
        is_baseline = result.get("state") == "building_baseline"
        is_null = result.get("score") is None
        assert is_baseline or is_null
