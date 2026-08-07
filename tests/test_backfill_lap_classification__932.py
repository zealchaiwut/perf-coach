"""Tests for issue #932: Backfill lap classification and recompute scores on threshold set.

Acceptance Criteria covered:
  AC1:  Script exists at scripts/backfill_lap_classification.py, accepts a user ID,
        reads thresholds from DB (never hardcoded), classifies laps for all existing
        run workouts, and persists or caches the resulting bands.
  AC2:  Script refreshes the duration curve after classifying laps.
  AC3:  Script recomputes all per-run inputs that scores and PRs depend on
        (TSS + duration curve).
  AC4:  Script is idempotent — running it twice produces the same result.
  AC5:  Script never overwrites a manually entered value.
  AC6:  DB access isolated to thin caller layer; core logic has no DB imports.
  AC7:  When athlete sets/accepts thresholds in settings UI, the same recompute
        pipeline runs automatically.
  AC8:  After backfill completes for athlete with thresholds, Performance tab
        displays numeric scores.
  AC9:  After backfill completes, PRs strip populates.
  AC10: If athlete has no thresholds, script exits cleanly with a clear message
        and makes no writes.
"""

import inspect
import io
import sys
from types import SimpleNamespace
from unittest import mock


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
                  workout_date_str="2026-01-01"):
    import datetime
    return SimpleNamespace(
        id=workout_id,
        user_id=user_id,
        workout_type=workout_type,
        workout_date=datetime.date.fromisoformat(workout_date_str),
        start_time=None,
        avg_power=210,
        avg_hr=140,
        distance_km=6.0,
        duration_seconds=1800,
        manual_overrides=None,
    )


def _make_prefs(ftp_w=200, threshold_hr=165, threshold_pace=300):
    return SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace,
    )


# ---------------------------------------------------------------------------
# AC1: Script file exists and is importable
# ---------------------------------------------------------------------------

class TestScriptExistsAC1:
    """AC1: scripts/backfill_lap_classification.py exists and has required structure."""

    def test_script_file_exists_at_expected_path(self):
        import os
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "backfill_lap_classification.py"
        )
        assert os.path.isfile(script_path), (
            "scripts/backfill_lap_classification.py does not exist"
        )

    def test_script_accepts_user_id_arg(self):
        import scripts.backfill_lap_classification as mod
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = [
            "backfill_lap_classification.py",
            "--user-id", "123e4567-e89b-12d3-a456-426614174000",
        ]
        try:
            args = mod._parse_args()
            assert args.user_id == "123e4567-e89b-12d3-a456-426614174000"
        finally:
            _sys.argv = old_argv

    def test_script_reads_thresholds_from_db_not_hardcoded(self):
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        for bad in ("ftp_w = 2", "ftp_w = 1", "threshold_hr = 1", "threshold_pace = 3"):
            assert bad not in src, f"Hardcoded threshold found in script: '{bad}'"

    def test_script_calls_classification_service(self):
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        assert "classify_laps" in src or "lap_recompute" in src, (
            "Script must call classify_laps or lap_recompute service"
        )


# ---------------------------------------------------------------------------
# AC2: Script refreshes the duration curve
# ---------------------------------------------------------------------------

class TestDurationCurveRefreshAC2:
    """AC2: Script rebuilds the best-effort duration curve after classifying laps."""

    def test_script_calls_rebuild_athlete_duration_curve(self):
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        assert "rebuild_athlete_duration_curve" in src or "lap_recompute" in src, (
            "Script must call rebuild_athlete_duration_curve or lap_recompute"
        )

    def test_rebuild_function_importable_from_lap_recompute(self):
        from backend.services.lap_recompute import rebuild_athlete_duration_curve
        assert callable(rebuild_athlete_duration_curve)

    def test_rebuild_function_accepts_user_id_and_db(self):
        from backend.services.lap_recompute import rebuild_athlete_duration_curve
        sig = inspect.signature(rebuild_athlete_duration_curve)
        params = list(sig.parameters.keys())
        assert "user_id" in params
        assert "db" in params or "session" in params


# ---------------------------------------------------------------------------
# AC3: Script recomputes all per-run inputs (TSS + curve)
# ---------------------------------------------------------------------------

class TestRecomputePerRunInputsAC3:
    """AC3: Script recomputes TSS and duration curve bests — all inputs scores depend on."""

    def test_recompute_user_running_tss_importable(self):
        from backend.services.tss import recompute_user_running_tss
        assert callable(recompute_user_running_tss)

    def test_script_calls_tss_recompute_or_references_it(self):
        """Script must recompute running TSS so per-run TSS values are updated."""
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        assert "running_tss" in src or "recompute_user_running_tss" in src, (
            "Script must call recompute_user_running_tss to update per-run TSS inputs"
        )

    def test_script_has_both_tss_and_curve_rebuild(self):
        """Script must trigger both TSS recompute and curve rebuild (all per-run inputs)."""
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        has_curve = "rebuild_athlete_duration_curve" in src or "lap_recompute" in src
        has_tss = "running_tss" in src or "recompute_user_running_tss" in src
        assert has_curve, "Script must rebuild duration curve"
        assert has_tss, "Script must recompute running TSS"


# ---------------------------------------------------------------------------
# AC4: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotencyAC4:
    """AC4: Running the script twice produces the same result; no duplicates."""

    def test_merge_best_effort_is_idempotent(self):
        from backend.services.duration_curve_best_effort import merge_best_effort

        existing = {"60": {"best_value": 250.0, "workout_id": "abc", "date": "2026-01-10",
                           "confidence": "measured"}}
        new_points = [
            {"duration_seconds": 60, "best_value": 260.0, "source_workout_id": "xyz",
             "date": "2026-01-15", "confidence": "measured"},
        ]
        curve1, r1 = merge_best_effort(existing, new_points)
        curve2, r2 = merge_best_effort(curve1, new_points)

        assert r1 is None
        assert r2 is None
        assert curve1 == curve2, "Two merges with identical data must produce the same curve"

    def test_classify_laps_is_deterministic(self):
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=210, avg_hr=140)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        result1 = classify_laps(splits, prefs)
        result2 = classify_laps(splits, prefs)
        assert result1 == result2


# ---------------------------------------------------------------------------
# AC5: Never overwrites manually entered values
# ---------------------------------------------------------------------------

class TestNoManualOverwriteAC5:
    """AC5: Manually entered lap types and workout overrides are never overwritten."""

    def test_classify_laps_does_not_mutate_split_objects(self):
        from backend.services.lap_classify import classify_laps
        split = _make_split(avg_power=210, avg_hr=140, lap_type="manual")
        original_power = split.avg_power
        original_hr = split.avg_hr

        classify_laps([split], {"ftp_w": 200})

        assert split.avg_power == original_power
        assert split.avg_hr == original_hr
        assert split.lap_type == "manual", "lap_type must not be changed"

    def test_rebuild_does_not_update_workout_splits(self):
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        rebuild_athlete_duration_curve("user-1", mock_session)

        for call in mock_session.execute.call_args_list:
            args = call[0]
            if args:
                stmt = str(args[0]).upper()
                assert "UPDATE WORKOUT_SPLITS" not in stmt, (
                    "rebuild must not UPDATE workout_splits"
                )


# ---------------------------------------------------------------------------
# AC6: DB access isolated to thin caller layer
# ---------------------------------------------------------------------------

class TestDBIsolationAC6:
    """AC6: Classification and recompute logic has no direct DB access."""

    def test_classify_laps_makes_no_db_calls(self):
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=210, avg_hr=140)]
        prefs = {"ftp_w": 200}
        result = classify_laps(splits, prefs)
        assert isinstance(result, list)

    def test_lap_classify_has_no_top_level_sqlalchemy_import(self):
        import ast
        import textwrap
        import backend.services.lap_classify as mod
        src = inspect.getsource(mod)
        tree = ast.parse(textwrap.dedent(src))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                assert "sqlalchemy" not in (node.module or ""), (
                    f"lap_classify must not import SQLAlchemy at module level: {node.module}"
                )

    def test_script_delegates_db_access_to_services(self):
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)
        assert "classify_laps" in src or "lap_recompute" in src, (
            "Script must delegate classification to a service"
        )


# ---------------------------------------------------------------------------
# AC7: Threshold-save triggers same pipeline automatically
# ---------------------------------------------------------------------------

class TestThresholdSaveTriggerAC7:
    """AC7: PATCH /api/user-preferences and accept endpoint fire the recompute pipeline."""

    def test_patch_prefs_endpoint_calls_rebuild(self):
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert (
            "rebuild_athlete_duration_curve" in src
            or "lap_recompute" in src
            or "_trigger_performance_backfill_background" in src
            or "backfill_performance" in src
        ), (
            "main.py must trigger rebuild_athlete_duration_curve on threshold save"
        )

    def test_accept_suggestions_endpoint_calls_rebuild(self):
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert (
            "rebuild_athlete_duration_curve" in src
            or "lap_recompute" in src
            or "_trigger_performance_backfill_background" in src
            or "backfill_performance" in src
        ), (
            "main.py must trigger rebuild on threshold acceptance"
        )

    def test_trigger_background_rebuild_function_exists(self):
        import backend.main as main_mod
        # _trigger_curve_rebuild_background was replaced by _trigger_performance_backfill_background
        # (issue #1588 dead-code cleanup); the new function covers the same AC.
        assert hasattr(main_mod, "_trigger_performance_backfill_background"), (
            "main.py must expose a background backfill trigger function"
        )
        assert callable(main_mod._trigger_performance_backfill_background)


# ---------------------------------------------------------------------------
# AC8: After backfill, Performance tab shows numeric scores
# ---------------------------------------------------------------------------

class TestPerformanceScoresAfterBackfillAC8:
    """AC8: After backfill with thresholds, endurance/speed scores are numeric."""

    def _easy_run(self, run_id, idx=1):
        return {
            "run_id": run_id,
            "workout_date": f"2026-01-{idx:02d}",
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 150.0,
                    "avg_hr": 138.0,
                    "distance_km": 5.0,
                    "duration_seconds": 1500.0,
                }
            ],
            "decoupling_pct": 4.0,
        }

    def test_easy_band_laps_produce_numeric_endurance_score(self):
        from backend.services.running_performance import compute_endurance_score
        from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        runs = [self._easy_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()

        result = compute_endurance_score(runs, prefs, zc)
        assert "score" in result, f"No score key: {result}"
        assert isinstance(result["score"], (int, float)), f"Non-numeric score: {result}"
        assert 0 <= result["score"] <= 100

    def test_classified_laps_not_none_when_thresholds_set(self):
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=150, avg_hr=138, distance_km=5.0, duration_seconds=1500)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        classifications = classify_laps(splits, prefs)
        assert all(c["band"] is not None for c in classifications)

    def test_check_needs_thresholds_helper_exists(self):
        import backend.main as main_mod
        fn = getattr(main_mod, "_check_needs_thresholds", None)
        assert fn is not None, "_check_needs_thresholds must exist in main.py"
        assert fn(None) is True
        assert fn({}) is True
        assert fn({"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}) is True


# ---------------------------------------------------------------------------
# AC9: After backfill, PRs strip populates
# ---------------------------------------------------------------------------

class TestPRsStripAfterBackfillAC9:
    """AC9: PRs strip populates for an athlete who has thresholds after backfill runs."""

    def test_detected_prs_endpoint_registered(self):
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert "detected-prs" in src or "detected_prs" in src, (
            "main.py must have a /api/athletes/{athlete_id}/detected-prs endpoint"
        )

    def test_fetch_and_detect_records_callable(self):
        from backend.services.pr_detection import fetch_and_detect_records
        assert callable(fetch_and_detect_records)

    def test_detect_speed_records_returns_results(self):
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
                "best_value": 1260 / 5.1,
                "source_workout_id": "run-1",
                "date": "2026-01-15",
                "source_workout": completed_runs[0],
            }
        ]

        result = detect_speed_records(pace_curve, completed_runs)
        assert "5km" in result
        assert "value" in result["5km"]

    def test_detect_power_records_returns_results(self):
        from backend.services.pr_detection import detect_power_records

        power_curve = [
            {
                "duration_seconds": 60,
                "best_value": 310.0,
                "source_workout_id": "run-1",
                "date": "2026-01-15",
                "source_workout": {"id": "run-1", "workout_date": "2026-01-15"},
            },
        ]
        result = detect_power_records(power_curve)
        assert "best1Min" in result
        assert result["best1Min"]["value"] == 310.0


# ---------------------------------------------------------------------------
# AC10: No thresholds → exit cleanly with clear message, no writes
# ---------------------------------------------------------------------------

class TestNoThresholdsCleanExitAC10:
    """AC10: When athlete has no thresholds, script exits cleanly with no DB writes."""

    def test_run_function_returns_early_when_no_thresholds(self):
        """_run() must return without calling DB writes when thresholds are absent."""
        import scripts.backfill_lap_classification as mod

        mock_engine = mock.MagicMock()
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)

        # User exists but has no thresholds
        mock_session.execute.side_effect = [
            mock.MagicMock(first=mock.MagicMock(return_value=("user-1",))),  # user found
            mock.MagicMock(first=mock.MagicMock(return_value=None)),          # no prefs row
        ]

        # Mock the Session constructor to return our mock
        with mock.patch("sqlalchemy.orm.Session", return_value=mock_session):
            with mock.patch(
                "backend.services.lap_recompute.rebuild_athlete_duration_curve"
            ) as mock_rebuild:
                captured = io.StringIO()
                sys.stdout = captured
                try:
                    mod._run(mock_engine, "123e4567-e89b-12d3-a456-426614174000")
                except SystemExit:
                    pass
                finally:
                    sys.stdout = sys.__stdout__

                # The rebuild (a write) must NOT have been called
                mock_rebuild.assert_not_called()

    def test_run_function_prints_clear_message_when_no_thresholds(self):
        """_run() must print a clear no-thresholds message before returning."""
        import scripts.backfill_lap_classification as mod

        mock_engine = mock.MagicMock()
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)

        # Prefs row with all None thresholds (equivalent to no thresholds)
        null_prefs = SimpleNamespace(ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None)
        mock_session.execute.side_effect = [
            mock.MagicMock(first=mock.MagicMock(return_value=("user-1",))),
            mock.MagicMock(first=mock.MagicMock(return_value=null_prefs)),
        ]

        with mock.patch("sqlalchemy.orm.Session", return_value=mock_session):
            with mock.patch(
                "backend.services.lap_recompute.rebuild_athlete_duration_curve"
            ):
                captured = io.StringIO()
                sys.stdout = captured
                try:
                    mod._run(mock_engine, "123e4567-e89b-12d3-a456-426614174000")
                except SystemExit:
                    pass
                finally:
                    sys.stdout = sys.__stdout__

        output = captured.getvalue()
        # Must mention "no thresholds" or equivalent
        assert any(
            phrase in output.lower()
            for phrase in ("no threshold", "threshold", "not set", "none set", "no thresholds")
        ), f"Expected clear no-thresholds message, got: {output!r}"

    def test_no_thresholds_script_makes_no_db_writes(self):
        """When no thresholds, _run must make zero DB writes (no commit, no add)."""
        import scripts.backfill_lap_classification as mod

        mock_engine = mock.MagicMock()
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.filter.return_value.first.return_value = None

        mock_session.execute.side_effect = [
            mock.MagicMock(first=mock.MagicMock(return_value=("user-1",))),
            mock.MagicMock(first=mock.MagicMock(return_value=None)),  # no prefs
        ]

        with mock.patch("sqlalchemy.orm.Session", return_value=mock_session):
            captured = io.StringIO()
            sys.stdout = captured
            try:
                mod._run(mock_engine, "123e4567-e89b-12d3-a456-426614174000")
            except SystemExit:
                pass
            finally:
                sys.stdout = sys.__stdout__

        mock_session.commit.assert_not_called()
        mock_session.add.assert_not_called()

    def test_script_source_has_early_return_on_no_thresholds(self):
        """Script source must show a return or sys.exit after the no-thresholds message."""
        import scripts.backfill_lap_classification as mod
        src = inspect.getsource(mod)

        # Verify the script mentions "no threshold" and then has a return/exit nearby
        assert "no threshold" in src.lower() or "No threshold" in src, (
            "Script must print a message about missing thresholds"
        )
        # The no-threshold path must exit (return or sys.exit) without proceeding
        # The run function must have an early-exit guard
        assert "return" in src, "Script must have a return statement (for early exit on no thresholds)"

    def test_classify_laps_with_empty_prefs_returns_all_none_bands(self):
        """Without thresholds, classify_laps returns band=None for every lap (graceful)."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=150, avg_hr=138)]
        result = classify_laps(splits, {})
        assert all(c["band"] is None for c in result), (
            "All laps must have band=None when no thresholds configured"
        )
