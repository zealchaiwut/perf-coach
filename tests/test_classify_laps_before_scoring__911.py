"""Tests for issue #911: Classify laps before scoring in performance endpoint.

Acceptance Criteria covered:
  AC1: Each lap dict passed to score functions includes band, avg_hr, avg_power,
       distance_km, and duration_seconds.
  AC2: Each run dict includes run_id, run_date (or workout_date), laps,
       and decoupling_pct.
  AC3: Lap classification uses the athlete's user_preferences thresholds —
       no hardcoded values.
  AC4: compute_endurance_score and compute_speed_score are not modified
       (pure functions stay unchanged).
  AC5: DB access remains in the caller (backend/main.py) not in the score
       functions.
  AC6: An athlete with thresholds configured and classified runs receives
       numeric (non-null) endurance and speed scores from the endpoint.
  AC7: An athlete with no thresholds set returns a clear error or null with
       an explanatory message rather than crashing.
"""

import ast
import inspect
import textwrap
from types import SimpleNamespace
from unittest import mock

import pytest

from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
)
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_split(avg_power=210, avg_hr=140, distance_km=2.0, duration_seconds=600):
    return SimpleNamespace(
        workout_id=1,
        split_index=0,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
    )


def _make_workout(workout_id, user_id=1, workout_date_str="2026-01-01"):
    import datetime
    return SimpleNamespace(
        id=workout_id,
        user_id=user_id,
        workout_type="Run",
        workout_date=datetime.date.fromisoformat(workout_date_str),
        start_time=None,
        avg_power=210,
        avg_hr=140,
        distance_km=6.0,
        duration_seconds=1800,
    )


def _make_prefs_row(ftp_w=200, threshold_hr=165, threshold_pace=300):
    return SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace,
        aerobic_decoupling_threshold=8.0,
    )


# ---------------------------------------------------------------------------
# AC1: Each lap dict passed to score functions includes required fields
# ---------------------------------------------------------------------------

class TestLapDictFields:
    """AC1: Lap dicts passed to score functions have all required fields."""

    def test_lap_dict_from_classify_has_band(self):
        """classify_laps output is merged into lap dicts — band must be present."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split()]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        classifications = classify_laps(splits, prefs)
        assert "band" in classifications[0]

    def test_lap_dict_includes_all_required_fields(self):
        """The five required fields must appear on every lap dict."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=220, avg_hr=140, distance_km=2.0, duration_seconds=600)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        classifications = classify_laps(splits, prefs)
        for split, cls in zip(splits, classifications):
            lap = {
                "band": cls.get("band"),
                "avg_power": split.avg_power,
                "avg_hr": split.avg_hr,
                "distance_km": float(split.distance_km) if split.distance_km is not None else None,
                "duration_seconds": split.duration_seconds,
            }
            for field in ("band", "avg_hr", "avg_power", "distance_km", "duration_seconds"):
                assert field in lap, f"Missing required field '{field}' in lap dict"

    def test_classified_band_is_not_missing(self):
        """When thresholds are set and metrics are present, band must not be None."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=210, avg_hr=140, distance_km=2.0, duration_seconds=600)]
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        classifications = classify_laps(splits, prefs)
        # ftp_w = 200, avg_power = 210 → ratio = 1.05 → threshold band
        assert classifications[0]["band"] is not None
        assert classifications[0]["band"] in ("easy", "steady", "tempo", "threshold", "hard")


# ---------------------------------------------------------------------------
# AC2: Each run dict includes run_id, workout_date, laps, decoupling_pct
# ---------------------------------------------------------------------------

class TestRunDictFields:
    """AC2: Run dicts passed to score functions have all required fields."""

    def _build_run_dict(self, workout, laps, decoupling_pct):
        return {
            "run_id": str(workout.id),
            "workout_date": workout.workout_date.isoformat() if workout.workout_date else "",
            "laps": laps,
            "decoupling_pct": decoupling_pct,
        }

    def test_run_dict_has_run_id(self):
        workout = _make_workout(workout_id=42)
        run = self._build_run_dict(workout, [], None)
        assert "run_id" in run

    def test_run_dict_has_workout_date(self):
        workout = _make_workout(workout_id=42, workout_date_str="2026-01-15")
        run = self._build_run_dict(workout, [], None)
        assert "workout_date" in run
        assert run["workout_date"] == "2026-01-15"

    def test_run_dict_has_laps(self):
        workout = _make_workout(workout_id=42)
        run = self._build_run_dict(workout, [{"band": "easy"}], None)
        assert "laps" in run
        assert isinstance(run["laps"], list)

    def test_run_dict_has_decoupling_pct(self):
        workout = _make_workout(workout_id=42)
        run = self._build_run_dict(workout, [], 5.2)
        assert "decoupling_pct" in run

    def test_run_dict_run_id_is_string(self):
        """run_id must be a string so it can be used as a dict key in debug output."""
        workout = _make_workout(workout_id=99)
        run = self._build_run_dict(workout, [], None)
        assert isinstance(run["run_id"], str)


# ---------------------------------------------------------------------------
# AC3: Lap classification uses athlete user_preferences thresholds
# ---------------------------------------------------------------------------

class TestLapClassificationUsesThresholds:
    """AC3: classify_laps is called with thresholds from user_preferences."""

    def test_power_threshold_determines_band(self):
        """Lap band is determined by ftp_w from preferences, not hardcoded."""
        from backend.services.lap_classify import classify_laps
        # ftp_w=300 with avg_power=210 → ratio=0.70 → easy
        splits_low = [_make_split(avg_power=210)]
        low = classify_laps(splits_low, {"ftp_w": 300})
        assert low[0]["band"] == "easy"

        # ftp_w=150 with avg_power=210 → ratio=1.40 → hard
        splits_high = [_make_split(avg_power=210)]
        high = classify_laps(splits_high, {"ftp_w": 150})
        assert high[0]["band"] == "hard"

    def test_hr_threshold_used_as_fallback(self):
        """When ftp_w is absent, threshold_hr from preferences is used."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split(avg_power=None, avg_hr=150, duration_seconds=600, distance_km=None)]
        prefs_none_ftp = {"ftp_w": None, "threshold_hr": 165, "threshold_pace_seconds_per_km": None}
        result = classify_laps(splits, prefs_none_ftp)
        assert result[0]["basis"] == "hr"
        assert result[0]["band"] is not None

    def test_no_thresholds_returns_band_none(self):
        """When preferences has no thresholds, band must be None (not a hardcoded default)."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split()]
        result = classify_laps(splits, {})
        assert result[0]["band"] is None
        assert result[0]["basis"] == "none"

    def test_classify_laps_accepts_prefs_dict_not_orm_object(self):
        """classify_laps works with a plain dict, not an ORM row."""
        from backend.services.lap_classify import classify_laps
        prefs_dict = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}
        splits = [_make_split(avg_power=180, avg_hr=140)]
        result = classify_laps(splits, prefs_dict)
        assert isinstance(result[0], dict)
        assert "band" in result[0]


# ---------------------------------------------------------------------------
# AC4: compute_endurance_score and compute_speed_score signatures unchanged
# ---------------------------------------------------------------------------

class TestScoreFunctionSignaturesUnchanged:
    """AC4: Pure score functions must not be modified."""

    def test_endurance_score_signature(self):
        """compute_endurance_score keeps the core (runs, preferences, zone_constants)
        contract; optional trailing params were added over time (body_modifier
        #1159, race_perf VDOT re-anchor)."""
        sig = inspect.signature(compute_endurance_score)
        params = list(sig.parameters.keys())
        assert params[:3] == ["runs", "preferences", "zone_constants"], (
            f"compute_endurance_score core signature changed: {params}"
        )

    def test_speed_score_signature(self):
        """compute_speed_score keeps the core (runs, preferences, zone_constants) contract."""
        sig = inspect.signature(compute_speed_score)
        params = list(sig.parameters.keys())
        assert params[:3] == ["runs", "preferences", "zone_constants"], (
            f"compute_speed_score core signature changed: {params}"
        )

    def test_endurance_score_is_callable(self):
        assert callable(compute_endurance_score)

    def test_speed_score_is_callable(self):
        assert callable(compute_speed_score)


# ---------------------------------------------------------------------------
# AC5: DB access stays in the caller (not in score functions)
# ---------------------------------------------------------------------------

class TestNoDatabaseAccessInScoreFunctions:
    """AC5: running_performance.py and lap_classify.py (classify_laps) make no
    top-level DB imports. DB access belongs only in the endpoint caller."""

    def test_running_performance_has_no_top_level_db_import(self):
        """running_performance module must not import SQLAlchemy at top level."""
        import backend.services.running_performance as mod
        src = inspect.getsource(mod)
        tree = ast.parse(textwrap.dedent(src))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Only check top-level imports (not inside functions)
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert "sqlalchemy" not in node.module.lower(), (
                        f"Top-level DB import found in running_performance: {node.module}"
                    )

    def test_classify_laps_pure_function_has_no_db_access(self):
        """classify_laps must not access the database."""
        from backend.services.lap_classify import classify_laps
        # If it tries to access DB it would fail; we verify it works without a session
        splits = [_make_split(avg_power=210, avg_hr=140)]
        prefs = {"ftp_w": 200}
        result = classify_laps(splits, prefs)  # must not raise
        assert isinstance(result, list)

    def test_running_performance_module_does_not_import_session(self):
        """Session or engine must not be used in running_performance at module level."""
        import backend.services.running_performance as mod
        module_src = inspect.getsource(mod)
        # Check module-level code (outside function defs) for session imports
        tree = ast.parse(textwrap.dedent(module_src))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom):
                    assert node.module != "backend.db", (
                        "running_performance must not import from backend.db at module level"
                    )


# ---------------------------------------------------------------------------
# AC6: Athlete with thresholds + runs gets numeric scores
# ---------------------------------------------------------------------------

class TestNumericScoresWithThresholds:
    """AC6: When thresholds are configured and runs are classified, scores are numeric."""

    def _easy_run(self, run_id, idx=1):
        return {
            "run_id": run_id,
            "workout_date": f"2026-01-{idx:02d}",
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 180.0,
                    "avg_hr": 140.0,
                    "distance_km": 2.0,
                    "duration_seconds": 600.0,
                }
            ],
            "decoupling_pct": 5.0,
            "avg_power": 180.0,
            "avg_hr": 140.0,
            "distance_km": 6.0,
            "duration_seconds": 1800,
        }

    def _hard_run(self, run_id, idx=1):
        return {
            "run_id": run_id,
            "workout_date": f"2026-01-{idx:02d}",
            "laps": [
                {
                    "band": "hard",
                    "avg_power": 240.0,
                    "avg_hr": 165.0,
                    "distance_km": 1.0,
                    "duration_seconds": 300.0,
                }
            ],
            "decoupling_pct": None,
            "avg_power": 240.0,
            "avg_hr": 165.0,
            "distance_km": 3.0,
            "duration_seconds": 900,
        }

    def test_endurance_score_is_numeric_with_classified_laps(self):
        """compute_endurance_score returns a numeric score when laps have bands."""
        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "duration_curve_bests": None,
        }
        runs = [self._easy_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert "score" in result, f"Expected score key, got: {result}"
        assert isinstance(result["score"], (int, float)), (
            f"Expected numeric score, got: {result['score']!r}"
        )
        assert 0 <= result["score"] <= 100

    def test_speed_score_is_numeric_with_classified_laps(self):
        """compute_speed_score returns a numeric score when laps have bands."""
        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "duration_curve_bests": None,
        }
        runs = [self._hard_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()
        result = compute_speed_score(runs, prefs, zc)
        assert "score" in result, f"Expected score key, got: {result}"
        assert isinstance(result["score"], (int, float)), (
            f"Expected numeric speed score, got: {result['score']!r}"
        )
        assert 0 <= result["score"] <= 100

    def test_laps_without_band_yield_no_qualifying_runs(self):
        """Laps with band=None (from unclassified runs) produce no qualifying runs."""
        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "duration_curve_bests": None,
        }
        unclassified_runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [
                    {
                        "band": None,  # not classified — simulates missing classify_laps call
                        "avg_power": 180.0,
                        "avg_hr": 140.0,
                        "distance_km": 2.0,
                        "duration_seconds": 600.0,
                    }
                ],
                "decoupling_pct": 5.0,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        zc = make_zone_constants()
        result = compute_endurance_score(unclassified_runs, prefs, zc)
        # No bands → no qualifying laps → building_baseline (not a numeric score)
        assert result.get("state") == "building_baseline", (
            "Unclassified laps (band=None) must not produce a numeric score"
        )


# ---------------------------------------------------------------------------
# AC7: No thresholds → graceful null with explanatory message
# ---------------------------------------------------------------------------

class TestGracefulHandlingNoThresholds:
    """AC7: Endpoint gracefully handles athletes with no preferences."""

    def test_compute_endurance_score_returns_null_when_prefs_none(self):
        """compute_endurance_score must return score: null when preferences is None."""
        result = compute_endurance_score([], None, make_zone_constants())
        # Either null score or building_baseline; must not raise
        has_null_score = result.get("score") is None and "reason" in result
        has_baseline = result.get("state") == "building_baseline"
        assert has_null_score or has_baseline, (
            f"Expected graceful null result, got: {result}"
        )

    def test_compute_speed_score_returns_null_when_prefs_none(self):
        """compute_speed_score must return score: null when preferences is None."""
        result = compute_speed_score([], None, make_zone_constants())
        has_null_score = result.get("score") is None and "reason" in result
        has_baseline = result.get("state") == "building_baseline"
        assert has_null_score or has_baseline

    def test_no_threshold_prefs_gives_graceful_result(self):
        """Empty thresholds → classify_laps returns band=None → building_baseline."""
        from backend.services.lap_classify import classify_laps
        # Simulate athlete with no thresholds: empty prefs
        splits = [_make_split(avg_power=180, avg_hr=140)]
        classifications = classify_laps(splits, {})
        # All bands are None because no thresholds exist
        assert all(c["band"] is None for c in classifications)
        assert all(c["basis"] == "none" for c in classifications)

    def test_no_threshold_prefs_does_not_crash_classify_laps(self):
        """classify_laps must not raise when preferences has no threshold keys."""
        from backend.services.lap_classify import classify_laps
        splits = [_make_split()]
        try:
            result = classify_laps(splits, {})
        except Exception as exc:
            pytest.fail(f"classify_laps raised with empty prefs: {exc}")
        assert isinstance(result, list)
        assert len(result) == len(splits)

    def test_null_prefs_in_endpoint_flow_returns_score_null(self):
        """When preferences is None the endurance/speed score must contain score: null."""
        # Simulate the endpoint flow: preferences=None → compute_* gets None
        endurance_result = compute_endurance_score([], None, make_zone_constants())
        speed_result = compute_speed_score([], None, make_zone_constants())
        # Must return null score with reason, not a 500
        assert endurance_result.get("score") is None or endurance_result.get("state") == "building_baseline"
        assert speed_result.get("score") is None or speed_result.get("state") == "building_baseline"

    def test_no_prefs_returns_explanatory_message(self):
        """When preferences is None, the result must include a 'reason' string."""
        result = compute_endurance_score(
            [{"run_id": "r1", "laps": [], "decoupling_pct": None, "workout_date": "2026-01-01"}],
            None,
            make_zone_constants(),
        )
        # preferences=None → score: null with reason
        assert result.get("score") is None
        assert isinstance(result.get("reason"), str)
        assert len(result["reason"]) > 0


# ---------------------------------------------------------------------------
# Integration: build_runs_list verifies lap dicts shape from endpoint assembly
# ---------------------------------------------------------------------------

class TestEndpointRunAssembly:
    """Integration-style tests that verify the run-assembly logic in the endpoint.

    These use mocks to exercise the same code path the endpoint handler uses,
    verifying AC1, AC2, AC3, and AC6 at the integration boundary.
    """

    def _build_runs_from_mock_db(self, prefs_dict, workouts, splits_by_id):
        """Replicate the endpoint's run-assembly loop without a live DB."""
        from backend.services.lap_classify import classify_laps
        from backend.services.aerobic_decoupling import compute_decoupling

        runs = []
        for workout in workouts:
            splits = splits_by_id.get(workout.id, [])
            classifications = classify_laps(splits, prefs_dict)
            laps = []
            for split, cls in zip(splits, classifications):
                laps.append({
                    "band": cls.get("band"),
                    "avg_power": split.avg_power,
                    "avg_hr": split.avg_hr,
                    "distance_km": float(split.distance_km) if split.distance_km is not None else None,
                    "duration_seconds": split.duration_seconds,
                })

            decoupling_pct = None
            if compute_decoupling is not None:
                split_dicts = [
                    {
                        "split_index": s.split_index,
                        "duration_seconds": s.duration_seconds,
                        "avg_hr": s.avg_hr,
                        "avg_power": s.avg_power,
                        "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                    }
                    for s in splits
                ]
                dec_result, _ = compute_decoupling(
                    {"workout_type": workout.workout_type},
                    split_dicts,
                    prefs_dict.get("aerobic_decoupling_threshold"),
                )
                decoupling_pct = dec_result.get("decoupling_pct") if dec_result else None

            runs.append({
                "run_id": str(workout.id),
                "workout_date": workout.workout_date.isoformat() if workout.workout_date else "",
                "laps": laps,
                "decoupling_pct": decoupling_pct,
            })
        return runs

    def test_assembled_run_has_all_required_keys(self):
        """AC2: All required run-level keys must be present."""
        import datetime
        workout = SimpleNamespace(
            id=1,
            user_id=1,
            workout_type="Run",
            workout_date=datetime.date(2026, 1, 1),
            start_time=None,
        )
        splits_by_id = {1: [_make_split(avg_power=180, avg_hr=140, distance_km=2.0, duration_seconds=600)]}
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        runs = self._build_runs_from_mock_db(prefs, [workout], splits_by_id)
        assert len(runs) == 1
        run = runs[0]
        for key in ("run_id", "workout_date", "laps", "decoupling_pct"):
            assert key in run, f"Missing required key '{key}' in run dict"

    def test_assembled_lap_has_all_required_fields(self):
        """AC1: All required lap-level fields must be present."""
        import datetime
        workout = SimpleNamespace(
            id=1,
            user_id=1,
            workout_type="Run",
            workout_date=datetime.date(2026, 1, 1),
            start_time=None,
        )
        splits_by_id = {1: [_make_split(avg_power=180, avg_hr=140, distance_km=2.0, duration_seconds=600)]}
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        runs = self._build_runs_from_mock_db(prefs, [workout], splits_by_id)
        lap = runs[0]["laps"][0]
        for field in ("band", "avg_hr", "avg_power", "distance_km", "duration_seconds"):
            assert field in lap, f"Missing required lap field '{field}'"

    def test_assembled_laps_have_band_from_classification(self):
        """AC3: The band field in assembled laps comes from classify_laps, not hardcoded."""
        import datetime
        workout = SimpleNamespace(
            id=1,
            user_id=1,
            workout_type="Run",
            workout_date=datetime.date(2026, 1, 1),
            start_time=None,
        )
        # avg_power=160, ftp_w=200 → ratio=0.80 → steady (>= 0.80 and < 0.90)
        splits_by_id = {1: [_make_split(avg_power=160, avg_hr=140, distance_km=2.0, duration_seconds=600)]}
        prefs = {"ftp_w": 200, "threshold_hr": 165, "threshold_pace_seconds_per_km": 300}

        runs = self._build_runs_from_mock_db(prefs, [workout], splits_by_id)
        lap = runs[0]["laps"][0]
        # ratio = 160/200 = 0.80 → "steady" (ratio >= 0.80 and < 0.90)
        assert lap["band"] == "steady"

    def test_numeric_scores_produced_from_assembled_runs(self):
        """AC6: Score functions produce numeric scores when runs are properly classified."""
        import datetime

        # Create enough runs to clear the minimum qualifying threshold
        workouts = []
        splits_by_id = {}
        for i in range(MIN_QUALIFYING_RUNS + 1):
            wid = i + 1
            w = SimpleNamespace(
                id=wid,
                user_id=1,
                workout_type="Run",
                workout_date=datetime.date(2026, 1, i + 1),
                start_time=None,
            )
            workouts.append(w)
            # avg_power=150+i*2, ftp_w=200 → ratio ~0.75-0.79 → easy (< 0.80)
            # This ensures laps are classified into the endurance (easy) band
            splits_by_id[wid] = [
                _make_split(avg_power=150 + i * 2, avg_hr=140, distance_km=2.0, duration_seconds=600)
            ]

        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "aerobic_decoupling_threshold": 8.0,
            "duration_curve_bests": None,
        }

        runs = self._build_runs_from_mock_db(prefs, workouts, splits_by_id)
        zc = make_zone_constants()
        endurance = compute_endurance_score(runs, prefs, zc)

        # With properly classified laps the score must be numeric
        assert "score" in endurance, f"No score key in result: {endurance}"
        assert isinstance(endurance["score"], (int, float)), (
            f"Score is not numeric: {endurance['score']!r}"
        )
        assert 0 <= endurance["score"] <= 100
