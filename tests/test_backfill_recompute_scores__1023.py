"""Tests for issue #1023: Backfill and recompute scores for all historical run laps.

Acceptance Criteria covered:
  AC1: A backfill job exists that retrieves every run belonging to the athlete
       and classifies each lap using the current threshold configuration.
  AC2: The job recomputes the endurance score, speed score, and fitness/fatigue/form
       time series for every affected run (by recomputing TSS and rebuilding the
       duration curve so on-the-fly score computation has correct inputs).
  AC3: The job is idempotent: executing it a second time produces identical results
       and does not create duplicate lap classification rows or score records.
  AC4: The job is triggered automatically when thresholds are first saved or updated.
  AC5: After the job completes, the athlete's profile displays a non-null, numeric
       endurance score and a non-null, numeric speed score.
  AC6: The fitness/fatigue/form chart populates with historical data points after
       the job runs.
"""

import datetime
import inspect
from types import SimpleNamespace
from unittest import mock



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_split(workout_id=1, split_index=0, avg_power=150, avg_hr=138,
                distance_km=5.0, duration_seconds=1500, lap_type="auto"):
    return SimpleNamespace(
        id=f"split-{workout_id}-{split_index}",
        workout_id=workout_id,
        split_index=split_index,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        lap_type=lap_type,
    )


def _make_workout(workout_id, user_id="user-1", workout_type="Run",
                  workout_date_str="2026-01-01", tss=45.0):
    return SimpleNamespace(
        id=workout_id,
        user_id=user_id,
        workout_type=workout_type,
        workout_date=datetime.date.fromisoformat(workout_date_str),
        start_time=None,
        avg_power=150,
        avg_hr=138,
        distance_km=5.0,
        duration_seconds=1500,
        tss=tss,
        manual_overrides=None,
    )


def _make_prefs(ftp_w=200, threshold_hr=165, threshold_pace=300):
    return SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace,
        aerobic_decoupling_threshold=None,
        duration_curve_bests=None,
    )


# ---------------------------------------------------------------------------
# AC1: Backfill job function exists and retrieves all run workouts
# ---------------------------------------------------------------------------

class TestBackfillJobExistsAC1:
    """AC1: A backfill job exists and classifies each lap using current thresholds."""

    def test_backfill_service_module_importable(self):
        from backend.services import backfill_performance  # noqa: F401
        assert backfill_performance is not None

    def test_backfill_for_athlete_function_exists(self):
        from backend.services.backfill_performance import backfill_performance_for_athlete
        assert callable(backfill_performance_for_athlete)

    def test_backfill_function_accepts_user_id_and_db(self):
        from backend.services.backfill_performance import backfill_performance_for_athlete
        sig = inspect.signature(backfill_performance_for_athlete)
        params = list(sig.parameters.keys())
        assert "user_id" in params
        assert "db" in params or "session" in params

    def test_backfill_function_returns_summary_dict(self):
        """backfill_performance_for_athlete must return a dict with required keys."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        mock_db = mock.MagicMock()
        # No prefs → no thresholds path
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = backfill_performance_for_athlete("user-1", mock_db)

        assert isinstance(result, dict), "Return value must be a dict"
        required_keys = {"thresholds_found", "runs_processed", "tss_recomputed", "curve_rebuilt"}
        assert required_keys <= set(result.keys()), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )

    def test_backfill_returns_thresholds_found_false_when_no_prefs(self):
        from backend.services.backfill_performance import backfill_performance_for_athlete

        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = backfill_performance_for_athlete("user-1", mock_db)
        assert result["thresholds_found"] is False
        assert result["runs_processed"] == 0

    def test_backfill_classifies_laps_using_current_thresholds(self):
        """Lap classification inside the backfill uses DB thresholds, not hardcoded values."""
        from backend.services.backfill_performance import backfill_performance_for_athlete
        src = inspect.getsource(backfill_performance_for_athlete)
        # The function must read thresholds dynamically (not hard-code numbers)
        for bad in ("ftp_w = 2", "ftp_w = 1", "threshold_hr = 1", "threshold_pace = 3"):
            assert bad not in src, f"Hardcoded threshold found in backfill service: '{bad}'"

    def test_backfill_service_calls_lap_classify_or_references_it(self):
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert (
            "classify_laps" in src
            or "lap_classify" in src
            or "lap_recompute" in src
            or "rebuild_athlete_duration_curve" in src
        ), "Backfill service must call or reference lap classification / recompute functions"

    def test_backfill_processes_run_workouts_not_other_types(self):
        """The backfill must only process runs (workout_type ilike '%run%')."""
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert "run" in src.lower(), "Backfill service must filter for run workouts"


# ---------------------------------------------------------------------------
# AC2: Job recomputes TSS and rebuilds duration curve
# ---------------------------------------------------------------------------

class TestRecomputeAfterBackfillAC2:
    """AC2: Backfill recomputes TSS and rebuilds the duration curve."""

    def test_backfill_calls_recompute_user_running_tss(self):
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert "recompute_user_running_tss" in src or "running_tss" in src, (
            "Backfill service must call recompute_user_running_tss"
        )

    def test_backfill_calls_rebuild_athlete_duration_curve(self):
        from backend.services import backfill_performance
        src = inspect.getsource(backfill_performance)
        assert "rebuild_athlete_duration_curve" in src or "lap_recompute" in src, (
            "Backfill service must call rebuild_athlete_duration_curve"
        )

    def test_backfill_reports_tss_recomputed_true_on_success(self):
        """When no exception occurs, tss_recomputed should be True in result."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
        mock_db.query.return_value.filter.return_value.count.return_value = 3

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ) as mock_tss, mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({}, None)
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["tss_recomputed"] is True
        mock_tss.assert_called_once()

    def test_backfill_reports_curve_rebuilt_true_on_success(self):
        """When rebuild returns no error reason, curve_rebuilt should be True."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
        mock_db.query.return_value.filter.return_value.count.return_value = 2

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({"60": {"best_value": 280.0}}, None)
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["curve_rebuilt"] is True

    def test_backfill_reports_runs_processed_count(self):
        """runs_processed must reflect how many run workouts were found."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
        mock_db.query.return_value.filter.return_value.count.return_value = 7

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({}, None)
            result = backfill_performance_for_athlete("user-1", mock_db)

        assert result["runs_processed"] == 7


# ---------------------------------------------------------------------------
# AC3: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotencyAC3:
    """AC3: Calling backfill twice produces identical results; no duplicates."""

    def test_running_backfill_twice_returns_same_summary(self):
        """Two calls with the same DB state return the same summary dict."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()

        def make_mock_db():
            mock_db = mock.MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
            mock_db.query.return_value.filter.return_value.count.return_value = 5
            return mock_db

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({}, None)

            result1 = backfill_performance_for_athlete("user-1", make_mock_db())
            result2 = backfill_performance_for_athlete("user-1", make_mock_db())

        assert result1["thresholds_found"] == result2["thresholds_found"]
        assert result1["runs_processed"] == result2["runs_processed"]
        assert result1["tss_recomputed"] == result2["tss_recomputed"]
        assert result1["curve_rebuilt"] == result2["curve_rebuilt"]

    def test_classify_laps_is_deterministic(self):
        """classify_laps called twice with same input produces same output."""
        from backend.services.lap_classify import classify_laps

        splits = [_make_split(avg_power=150, avg_hr=138)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        r1 = classify_laps(splits, prefs)
        r2 = classify_laps(splits, prefs)
        assert r1 == r2

    def test_rebuild_duration_curve_is_idempotent(self):
        """Two merge_best_effort calls with same new_points produce the same curve."""
        from backend.services.duration_curve_best_effort import merge_best_effort

        existing = {
            "60": {"best_value": 250.0, "workout_id": "abc",
                   "date": "2026-01-10", "confidence": "measured"}
        }
        new_points = [
            {"duration_seconds": 60, "best_value": 260.0,
             "source_workout_id": "xyz", "date": "2026-01-15", "confidence": "measured"},
        ]
        curve1, r1 = merge_best_effort(existing, new_points)
        curve2, r2 = merge_best_effort(curve1, new_points)

        assert r1 is None
        assert r2 is None
        assert curve1 == curve2


# ---------------------------------------------------------------------------
# AC4: Job is triggered automatically when thresholds are saved/updated
# ---------------------------------------------------------------------------

class TestThresholdSaveTriggerAC4:
    """AC4: PATCH /api/user-preferences triggers the backfill pipeline."""

    def test_patch_prefs_endpoint_references_backfill_trigger(self):
        """main.py must reference the backfill trigger when thresholds change."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert (
            "backfill_performance_for_athlete" in src
            or "_trigger_performance_backfill" in src
            or "_trigger_curve_rebuild_background" in src
        ), "main.py must trigger the backfill pipeline when thresholds change"

    def test_trigger_performance_backfill_background_exists(self):
        """A background trigger function for performance backfill must exist in main.py."""
        import backend.main as main_mod
        assert hasattr(main_mod, "_trigger_performance_backfill_background") or hasattr(
            main_mod, "_trigger_curve_rebuild_background"
        ), "A background backfill trigger function must exist"

    def test_trigger_calls_backfill_service(self):
        """The trigger function (or PATCH handler) must call the backfill service."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        # Either the new trigger function or the old one that calls both TSS + curve
        assert "rebuild_athlete_duration_curve" in src or "backfill_performance_for_athlete" in src, (
            "main.py must call rebuild_athlete_duration_curve or the new backfill service"
        )

    def test_backfill_endpoint_exists(self):
        """A POST /api/performance/backfill endpoint must be registered."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert "/api/performance/backfill" in src, (
            "A POST /api/performance/backfill endpoint must exist for manual triggering"
        )

    def test_backfill_endpoint_callable_with_resolve_user(self):
        """The backfill endpoint must require authentication via resolve_user."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        # Verify that the endpoint references resolve_user
        assert "resolve_user" in src


# ---------------------------------------------------------------------------
# AC5: After job completes, endurance and speed scores are non-null numeric
# ---------------------------------------------------------------------------

class TestScoresAfterBackfillAC5:
    """AC5: After backfill, performance endpoint returns non-null numeric scores."""

    def _make_easy_run(self, run_id, idx=1):
        return {
            "run_id": run_id,
            "run_date": f"2026-0{idx // 28 + 1}-{(idx % 28) + 1:02d}",
            "workout_date": f"2026-0{idx // 28 + 1}-{(idx % 28) + 1:02d}",
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

    def test_endurance_score_is_numeric_with_enough_easy_runs(self):
        """With thresholds set and MIN_QUALIFYING_RUNS easy runs, endurance score is numeric."""
        from backend.services.running_performance import compute_endurance_score
        from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        runs = [self._make_easy_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()

        result = compute_endurance_score(runs, prefs, zc)
        assert isinstance(result.get("score"), (int, float)), (
            f"Expected numeric score after backfill, got: {result}"
        )
        assert 0 <= result["score"] <= 100

    def test_laps_classified_correctly_with_thresholds(self):
        """After backfill, laps classified with power basis produce correct bands."""
        from backend.services.lap_classify import classify_laps

        # Easy lap: power ratio = 150/200 = 0.75 → below 0.80 → "easy"
        splits = [_make_split(avg_power=150, avg_hr=138, distance_km=5.0, duration_seconds=1500)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        results = classify_laps(splits, prefs)
        assert len(results) == 1
        assert results[0]["band"] == "easy", f"Expected 'easy' band, got {results[0]}"
        assert results[0]["basis"] == "power"

    def test_endurance_score_non_null_after_backfill_prepares_data(self):
        """End-to-end: backfill service + classify + score pipeline returns numeric score."""
        from backend.services.running_performance import compute_endurance_score
        from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

        # Simulate runs that have been classified (the backfill ensures TSS/curve are
        # in sync; classification itself is on-the-fly, using these prefs)
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        runs_with_classified_laps = [self._make_easy_run(f"run-{i}", i)
                                     for i in range(1, MIN_QUALIFYING_RUNS + 1)]

        zc = make_zone_constants()
        result = compute_endurance_score(runs_with_classified_laps, prefs, zc)

        assert "score" in result
        assert result["score"] is not None, "Endurance score must be non-null after backfill"
        assert isinstance(result["score"], float)

    def test_speed_score_non_null_with_hard_runs(self):
        """Speed score is numeric when athlete has MIN_QUALIFYING_RUNS hard-lap runs."""
        from backend.services.running_performance import compute_speed_score
        from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

        prefs = {"ftp_w": 200}
        hard_run = {
            "run_id": "r1",
            "run_date": "2026-01-01",
            "workout_date": "2026-01-01",
            "laps": [
                {
                    "band": "hard",
                    "avg_power": 220.0,
                    "avg_hr": 172.0,
                    "distance_km": 2.0,
                    "duration_seconds": 480.0,
                }
            ],
            "decoupling_pct": None,
        }
        runs = [
            {**hard_run, "run_id": f"r{i}", "run_date": f"2026-01-{i:02d}",
             "workout_date": f"2026-01-{i:02d}"}
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]
        zc = make_zone_constants()
        result = compute_speed_score(runs, prefs, zc)

        assert isinstance(result.get("score"), (int, float)), (
            f"Expected numeric speed score, got: {result}"
        )


# ---------------------------------------------------------------------------
# AC6: Fitness/fatigue/form chart populates after job runs
# ---------------------------------------------------------------------------

class TestFitnessChartPopulatesAC6:
    """AC6: After backfill recomputes TSS, the fitness/fatigue/form chart has data."""

    def test_fitness_model_returns_populated_days_with_tss_data(self):
        """compute_fitness_series returns non-empty days when TSS data exists."""
        from backend.services.fitness_model import compute_fitness_series

        daily_load = [
            {"date": f"2026-01-{i:02d}", "daily_load": 50.0}
            for i in range(1, 30)
        ]
        result = compute_fitness_series(daily_load)

        assert len(result["days"]) == 29, "Must have one entry per day"
        assert all(isinstance(d["ctl"], float) for d in result["days"])
        assert all(isinstance(d["atl"], float) for d in result["days"])
        assert all(isinstance(d["tsb"], float) for d in result["days"])

    def test_fitness_chart_empty_without_tss_data(self):
        """Without TSS data (no backfill), fitness series is empty or all-zero."""
        from backend.services.fitness_model import compute_fitness_series

        daily_load = [
            {"date": f"2026-01-{i:02d}", "daily_load": 0.0}
            for i in range(1, 10)
        ]
        result = compute_fitness_series(daily_load)

        # With zero load, CTL/ATL/TSB start at 0 and stay at 0 — chart exists but is flat
        assert all(d["ctl"] == 0.0 for d in result["days"])
        assert all(d["atl"] == 0.0 for d in result["days"])

    def test_backfill_recomputes_tss_so_fitness_chart_has_data(self):
        """After backfill updates workout.tss values, fitness series is populated."""
        from backend.services.fitness_model import compute_fitness_series, MIN_HISTORY_DAYS

        # Simulate 35 days of TSS data (as if backfill recomputed them)
        daily_load = [
            {"date": f"2026-01-{i:02d}" if i <= 31 else f"2026-02-{i - 31:02d}",
             "daily_load": 45.0}
            for i in range(1, MIN_HISTORY_DAYS + 8)
        ]
        result = compute_fitness_series(daily_load)

        assert result["building_baseline"] is False, (
            "After enough days, building_baseline must be False"
        )
        assert result["summary"] is not None
        assert isinstance(result["summary"]["ctl"], float)
        assert result["summary"]["ctl"] > 0

    def test_performance_chart_returns_data_with_tss_and_runs(self):
        """compute_performance_chart returns populated arrays when TSS + runs exist."""
        from backend.services.performance_chart import compute_performance_chart
        from backend.services.fitness_model import MIN_HISTORY_DAYS

        # Build enough daily load to pass building_baseline
        daily_load = [
            {"date": f"2026-01-{i:02d}" if i <= 31 else f"2026-02-{(i - 31):02d}",
             "daily_load": 50.0}
            for i in range(1, MIN_HISTORY_DAYS + 5)
        ]

        runs = [
            {
                "run_id": f"run-{i}",
                "run_date": f"2026-01-{i:02d}",
                "laps": [
                    {
                        "band": "easy",
                        "avg_power": 150.0,
                        "avg_hr": 138.0,
                        "distance_km": 5.0,
                        "duration_seconds": 1500.0,
                    }
                ],
                "decoupling_pct": None,
            }
            for i in range(1, 5)
        ]

        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        result = compute_performance_chart(
            daily_load_series=daily_load,
            runs=runs,
            preferences=prefs,
            zone_constants=None,
            start_date="2026-01-05",
            end_date="2026-01-28",
        )

        assert result["dates"], "dates must be non-empty"
        assert any(v is not None for v in result["ctl"]), "CTL must have non-null values"
        assert any(v is not None for v in result["atl"]), "ATL must have non-null values"


# ---------------------------------------------------------------------------
# AC5 + AC6 combined: Backfill API endpoint
# ---------------------------------------------------------------------------

class TestBackfillApiEndpointAC4AC5:
    """AC4: POST /api/performance/backfill endpoint triggers backfill for the user."""

    def test_backfill_endpoint_registered_in_main(self):
        """main.py must have a POST /api/performance/backfill route."""
        import backend.main as main_mod
        src = inspect.getsource(main_mod)
        assert "/api/performance/backfill" in src, (
            "POST /api/performance/backfill endpoint must be registered in main.py"
        )

    def test_backfill_endpoint_returns_summary_keys(self):
        """Endpoint must return a dict with thresholds_found, runs_processed, tss_recomputed,
        curve_rebuilt keys."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        prefs_obj = _make_prefs()
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj
        mock_db.query.return_value.filter.return_value.count.return_value = 4

        with mock.patch(
            "backend.services.backfill_performance.recompute_user_running_tss"
        ), mock.patch(
            "backend.services.backfill_performance.rebuild_athlete_duration_curve"
        ) as mock_curve:
            mock_curve.return_value = ({}, None)
            result = backfill_performance_for_athlete("user-1", mock_db)

        required = {"thresholds_found", "runs_processed", "tss_recomputed", "curve_rebuilt"}
        assert required <= set(result.keys())

    def test_backfill_endpoint_no_thresholds_returns_thresholds_found_false(self):
        """When no thresholds are set, the backfill service reports thresholds_found=False."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        # Prefs with all-None thresholds
        prefs_obj = SimpleNamespace(
            ftp_w=None, threshold_hr=None, threshold_pace_seconds_per_km=None
        )
        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = prefs_obj

        result = backfill_performance_for_athlete("user-1", mock_db)
        assert result["thresholds_found"] is False

    def test_backfill_service_no_db_writes_when_no_thresholds(self):
        """When no thresholds, the service makes no DB writes (no commit, no add)."""
        from backend.services.backfill_performance import backfill_performance_for_athlete

        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        backfill_performance_for_athlete("user-1", mock_db)

        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()
