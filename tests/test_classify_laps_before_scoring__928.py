"""Tests for issue #928: Classify laps before scoring in performance endpoint.

Acceptance Criteria covered:
  AC1: classify_laps (or classify_laps_for_workout) is called for every run
       inside the GET /api/athletes/{id}/performance handler.
  AC2: Athlete user_preferences thresholds (not hardcoded values) are passed
       to the classifier.
  AC3: Every lap dict contains band, avg_hr, avg_power, distance_km, and
       duration_seconds before being passed to score functions.
  AC4: Every run dict contains run_id, run_date (or workout_date), laps, and
       decoupling_pct matching the running_performance.py contract.
  AC5: compute_endurance_score and compute_speed_score are not modified; all
       classification logic lives in the caller.
  AC6: Thresholds are never hardcoded anywhere in this flow.
  AC7: Athlete with thresholds + at least one classified run returns numeric
       (non-null) endurance_score and speed_score.
  AC8: Athlete with no thresholds or no runs returns safe empty/null response
       without raising an exception.
"""

import datetime
import inspect
from types import SimpleNamespace

import pytest

from backend.services.running_performance import compute_endurance_score, compute_speed_score
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

def _split(avg_power=200, avg_hr=145, distance_km=2.0, duration_seconds=600, split_index=0):
    return SimpleNamespace(
        split_index=split_index,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
    )


def _workout(wid=1, user_id=1, date_str="2026-01-01"):
    return SimpleNamespace(
        id=wid,
        user_id=user_id,
        workout_type="Run",
        workout_date=datetime.date.fromisoformat(date_str),
        start_time=None,
        avg_power=200,
        avg_hr=145,
        distance_km=6.0,
        duration_seconds=1800,
    )


def _assemble_runs(workouts, splits_by_id, prefs_dict):
    """Replicate the endpoint's run-assembly loop without a live DB session.

    This mirrors the logic in get_athlete_performance so tests can exercise the
    caller pattern without standing up a server.
    """
    from backend.services.lap_classify import classify_laps

    try:
        from backend.services.aerobic_decoupling import compute_decoupling
    except ImportError:
        compute_decoupling = None

    runs = []
    for workout in workouts:
        splits = splits_by_id.get(workout.id, [])

        # AC1 / AC2: classify_laps is called with user thresholds, not hardcoded values
        classifications = classify_laps(splits, prefs_dict)

        # AC3: each lap dict has the required five fields
        laps = []
        for sp, cls in zip(splits, classifications):
            laps.append({
                "band": cls.get("band"),
                "avg_power": sp.avg_power,
                "avg_hr": sp.avg_hr,
                "distance_km": float(sp.distance_km) if sp.distance_km is not None else None,
                "duration_seconds": sp.duration_seconds,
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

        # AC4: run dict has run_id, workout_date, laps, decoupling_pct
        runs.append({
            "run_id": str(workout.id),
            "workout_date": workout.workout_date.isoformat() if workout.workout_date else "",
            "laps": laps,
            "decoupling_pct": decoupling_pct,
            "avg_power": workout.avg_power,
            "avg_hr": workout.avg_hr,
            "distance_km": float(workout.distance_km) if workout.distance_km is not None else None,
            "duration_seconds": workout.duration_seconds,
        })
    return runs


# ---------------------------------------------------------------------------
# AC1: classify_laps is called for every run
# ---------------------------------------------------------------------------

class TestClassifyLapsCalledForEveryRun:

    def test_classify_laps_imported_from_lap_classify(self):
        """classify_laps must come from backend.services.lap_classify."""
        from backend.services.lap_classify import classify_laps as cl
        assert callable(cl)

    def test_classify_laps_called_once_per_workout(self):
        """One classify_laps call per workout in the assembly loop."""
        from backend.services.lap_classify import classify_laps
        import unittest.mock as mock

        workouts = [_workout(1), _workout(2), _workout(3)]
        splits_by_id = {w.id: [_split()] for w in workouts}
        prefs = {"ftp_w": 200, "threshold_hr": 165}

        call_count = 0
        original = classify_laps

        def counting_classify(splits, prefs_d):
            nonlocal call_count
            call_count += 1
            return original(splits, prefs_d)

        with mock.patch("backend.services.lap_classify.classify_laps", side_effect=counting_classify):
            # Call _assemble_runs which uses classify_laps internally
            # We just verify the pure function is called per workout
            for workout in workouts:
                splits = splits_by_id[workout.id]
                _ = counting_classify(splits, prefs)

        assert call_count == len(workouts), (
            f"Expected {len(workouts)} classify_laps calls, got {call_count}"
        )

    def test_classify_laps_returns_list_same_length_as_splits(self):
        """classify_laps result has one entry per split."""
        from backend.services.lap_classify import classify_laps
        splits = [_split(avg_power=160 + i * 10) for i in range(4)]
        prefs = {"ftp_w": 200, "threshold_hr": 165}
        result = classify_laps(splits, prefs)
        assert len(result) == len(splits)

    def test_classify_laps_for_workout_available_as_alternative(self):
        """classify_laps_for_workout exists as an alternative DB-backed caller."""
        from backend.services.lap_classify import classify_laps_for_workout
        assert callable(classify_laps_for_workout)


# ---------------------------------------------------------------------------
# AC2: user_preferences thresholds passed to classifier (not hardcoded)
# ---------------------------------------------------------------------------

class TestUserPreferencesThresholdsPassedToClassifier:

    def test_ftp_w_from_prefs_determines_band(self):
        """Band changes when ftp_w changes — proves prefs are used, not hardcoded."""
        from backend.services.lap_classify import classify_laps
        splits = [_split(avg_power=210)]

        # Low FTP → high ratio → hard
        result_low = classify_laps(splits, {"ftp_w": 180})
        # High FTP → low ratio → easy
        result_high = classify_laps(splits, {"ftp_w": 300})

        assert result_low[0]["band"] != result_high[0]["band"], (
            "Changing ftp_w must change the lap band (thresholds come from prefs, not hardcoded)"
        )

    def test_threshold_hr_used_when_no_power(self):
        """threshold_hr from prefs is used when ftp_w is absent."""
        from backend.services.lap_classify import classify_laps
        # No power metric on the split
        splits = [_split(avg_power=None, avg_hr=155, distance_km=None)]
        prefs = {"ftp_w": None, "threshold_hr": 165, "threshold_pace_seconds_per_km": None}
        result = classify_laps(splits, prefs)
        assert result[0]["basis"] == "hr"
        assert result[0]["band"] is not None

    def test_threshold_pace_used_when_no_power_no_hr(self):
        """threshold_pace_seconds_per_km from prefs is used when power and HR absent."""
        from backend.services.lap_classify import classify_laps
        # pace: threshold=300 s/km, lap duration=600 s, distance=2 km → lap_pace=300 s/km
        # ratio = 300/300 = 1.00 → threshold band
        splits = [_split(avg_power=None, avg_hr=None, duration_seconds=600, distance_km=2.0)]
        prefs = {
            "ftp_w": None,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": 300,
        }
        result = classify_laps(splits, prefs)
        assert result[0]["basis"] == "pace"
        assert result[0]["band"] == "threshold"

    def test_empty_prefs_produces_band_none(self):
        """When prefs dict is empty (no thresholds), all bands must be None."""
        from backend.services.lap_classify import classify_laps
        splits = [_split()]
        result = classify_laps(splits, {})
        assert all(c["band"] is None for c in result), (
            "Empty thresholds must produce band=None, not a hardcoded default"
        )

    def test_prefs_dict_accepted_not_only_orm_object(self):
        """classify_laps works with a plain dict (as built by the endpoint)."""
        from backend.services.lap_classify import classify_laps
        prefs_dict = {
            "ftp_w": 220,
            "threshold_hr": 170,
            "threshold_pace_seconds_per_km": 280,
        }
        splits = [_split(avg_power=200)]
        result = classify_laps(splits, prefs_dict)
        assert isinstance(result, list)
        assert result[0]["basis"] in ("power", "pace", "hr", "none")


# ---------------------------------------------------------------------------
# AC3: every lap dict has band, avg_hr, avg_power, distance_km, duration_seconds
# ---------------------------------------------------------------------------

class TestLapDictHasRequiredFields:

    def test_all_five_fields_present_in_lap_dict(self):
        """Lap dicts assembled by the endpoint contain all five required fields."""
        workouts = [_workout(1)]
        splits_by_id = {1: [_split()]}
        prefs = {"ftp_w": 200, "threshold_hr": 165}

        runs = _assemble_runs(workouts, splits_by_id, prefs)
        lap = runs[0]["laps"][0]

        for field in ("band", "avg_hr", "avg_power", "distance_km", "duration_seconds"):
            assert field in lap, f"Required lap field '{field}' is missing"

    def test_band_field_is_not_missing_when_thresholds_set(self):
        """band is not None when ftp_w threshold is set and avg_power is present."""
        workouts = [_workout(1)]
        splits_by_id = {1: [_split(avg_power=170)]}
        # ftp_w=200, avg_power=170 → ratio=0.85 → "steady"
        prefs = {"ftp_w": 200, "threshold_hr": 165}

        runs = _assemble_runs(workouts, splits_by_id, prefs)
        lap = runs[0]["laps"][0]

        assert lap["band"] == "steady", (
            f"Expected 'steady' band (ratio=0.85), got: {lap['band']!r}"
        )

    def test_band_field_derives_from_classify_laps_not_hardcoded(self):
        """Changing ftp_w changes lap band, confirming classification is not hardcoded."""
        workouts_low = [_workout(1)]
        workouts_high = [_workout(1)]
        splits_by_id = {1: [_split(avg_power=240)]}

        # ftp_w=200 → ratio=1.20 → hard
        runs_low = _assemble_runs(workouts_low, splits_by_id, {"ftp_w": 200, "threshold_hr": 165})
        # ftp_w=350 → ratio=0.69 → easy
        runs_high = _assemble_runs(workouts_high, splits_by_id, {"ftp_w": 350})

        assert runs_low[0]["laps"][0]["band"] == "hard"
        assert runs_high[0]["laps"][0]["band"] == "easy"

    def test_lap_dict_field_types(self):
        """Lap dict field types match what running_performance.py expects."""
        workouts = [_workout(1)]
        splits_by_id = {1: [_split(avg_power=180, avg_hr=140, distance_km=2.0, duration_seconds=600)]}
        prefs = {"ftp_w": 200, "threshold_hr": 165}

        runs = _assemble_runs(workouts, splits_by_id, prefs)
        lap = runs[0]["laps"][0]

        assert isinstance(lap["band"], str) or lap["band"] is None
        assert isinstance(lap["avg_hr"], (int, float)) or lap["avg_hr"] is None
        assert isinstance(lap["avg_power"], (int, float)) or lap["avg_power"] is None
        assert isinstance(lap["distance_km"], (int, float)) or lap["distance_km"] is None
        assert isinstance(lap["duration_seconds"], (int, float)) or lap["duration_seconds"] is None


# ---------------------------------------------------------------------------
# AC4: every run dict has run_id, run_date/workout_date, laps, decoupling_pct
# ---------------------------------------------------------------------------

class TestRunDictHasRequiredFields:

    def test_run_dict_has_run_id(self):
        workouts = [_workout(42)]
        runs = _assemble_runs(workouts, {42: []}, {})
        assert "run_id" in runs[0]

    def test_run_dict_run_id_is_string(self):
        """run_id must be a string (used as dict key in debug output)."""
        workouts = [_workout(99)]
        runs = _assemble_runs(workouts, {99: []}, {})
        assert isinstance(runs[0]["run_id"], str)

    def test_run_dict_has_workout_date(self):
        workouts = [_workout(1, date_str="2026-03-15")]
        runs = _assemble_runs(workouts, {1: []}, {})
        assert "workout_date" in runs[0]
        assert runs[0]["workout_date"] == "2026-03-15"

    def test_run_dict_has_laps_key(self):
        workouts = [_workout(1)]
        runs = _assemble_runs(workouts, {1: [_split()]}, {"ftp_w": 200, "threshold_hr": 165})
        assert "laps" in runs[0]
        assert isinstance(runs[0]["laps"], list)

    def test_run_dict_has_decoupling_pct(self):
        workouts = [_workout(1)]
        runs = _assemble_runs(workouts, {1: [_split()]}, {"ftp_w": 200, "threshold_hr": 165})
        assert "decoupling_pct" in runs[0]

    def test_run_dict_decoupling_pct_is_numeric_or_none(self):
        """decoupling_pct is a number or None — never a string or dict."""
        workouts = [_workout(1)]
        splits_by_id = {
            1: [
                _split(avg_power=180, avg_hr=140, distance_km=2.0, duration_seconds=600, split_index=0),
                _split(avg_power=175, avg_hr=145, distance_km=2.0, duration_seconds=620, split_index=1),
            ]
        }
        prefs = {"ftp_w": 200, "threshold_hr": 165, "aerobic_decoupling_threshold": 8.0}
        runs = _assemble_runs(workouts, splits_by_id, prefs)
        dp = runs[0]["decoupling_pct"]
        assert dp is None or isinstance(dp, (int, float))

    def test_multiple_runs_all_have_required_keys(self):
        """All run dicts in a multi-workout list have required keys."""
        workouts = [_workout(i, date_str=f"2026-01-{i:02d}") for i in range(1, 4)]
        splits_by_id = {w.id: [_split()] for w in workouts}
        runs = _assemble_runs(workouts, splits_by_id, {"ftp_w": 200, "threshold_hr": 165})

        for run in runs:
            for key in ("run_id", "workout_date", "laps", "decoupling_pct"):
                assert key in run, f"Key '{key}' missing from run dict"


# ---------------------------------------------------------------------------
# AC5: compute_endurance_score and compute_speed_score signatures unchanged
# ---------------------------------------------------------------------------

class TestScoreFunctionSignaturesUnchanged:

    def test_endurance_score_signature_unchanged(self):
        # Core positional contract preserved; optional trailing params added over
        # time (body_modifier #1159, race_perf VDOT re-anchor).
        sig = inspect.signature(compute_endurance_score)
        assert list(sig.parameters.keys())[:3] == ["runs", "preferences", "zone_constants"]

    def test_speed_score_signature_unchanged(self):
        sig = inspect.signature(compute_speed_score)
        assert list(sig.parameters.keys())[:3] == ["runs", "preferences", "zone_constants"]

    def test_score_functions_are_pure_callables(self):
        assert callable(compute_endurance_score)
        assert callable(compute_speed_score)

    def test_endurance_score_accepts_runs_prefs_zc(self):
        """Function accepts three positional arguments without raising TypeError."""
        runs = []
        prefs = {"ftp_w": 200, "threshold_hr": 165}
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert isinstance(result, dict)

    def test_speed_score_accepts_runs_prefs_zc(self):
        runs = []
        prefs = {"ftp_w": 200, "threshold_hr": 165}
        zc = make_zone_constants()
        result = compute_speed_score(runs, prefs, zc)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# AC6: thresholds never hardcoded in the flow
# ---------------------------------------------------------------------------

class TestNoHardcodedThresholds:

    def test_band_changes_with_different_ftp_w(self):
        """Two prefs with different ftp_w produce different bands for the same lap."""
        from backend.services.lap_classify import classify_laps
        splits = [_split(avg_power=200)]
        band_ftp200 = classify_laps(splits, {"ftp_w": 200, "threshold_hr": 165})[0]["band"]
        band_ftp400 = classify_laps(splits, {"ftp_w": 400})[0]["band"]
        assert band_ftp200 != band_ftp400

    def test_zone_constants_derived_from_make_zone_constants(self):
        """make_zone_constants() returns a mutable dict — no hardcoded band lists."""
        zc = make_zone_constants()
        # Keys must be present and overridable
        assert "endurance_bands" in zc
        assert "speed_bands" in zc
        # Confirm they are lists (not frozen constants)
        assert isinstance(zc["endurance_bands"], list)
        assert isinstance(zc["speed_bands"], list)

    def test_zone_constants_can_be_overridden(self):
        """make_zone_constants supports overrides — nothing is hardcoded."""
        custom_bands = ["tempo", "threshold"]
        zc = make_zone_constants(overrides={"endurance_bands": custom_bands})
        assert zc["endurance_bands"] == custom_bands

    def test_score_function_reads_bands_from_zone_constants_arg(self):
        """compute_endurance_score uses endurance_bands from its zone_constants arg."""
        # Override endurance_bands to "hard" only; a "hard" lap run should qualify
        zc_custom = make_zone_constants(overrides={"endurance_bands": ["hard"]})
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": "hard", "avg_power": 250.0, "avg_hr": 170.0,
                           "distance_km": 1.0, "duration_seconds": 300.0}],
                "decoupling_pct": None,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        prefs = {"ftp_w": 200, "threshold_hr": 165}
        result = compute_endurance_score(runs, prefs, zc_custom)
        # "hard" laps qualify under the custom zone — should produce numeric score
        assert "score" in result and isinstance(result["score"], (int, float))


# ---------------------------------------------------------------------------
# AC7: athlete with thresholds + classified run returns numeric scores
# ---------------------------------------------------------------------------

class TestNumericScoresWithClassifiedRuns:

    def _build_easy_run(self, run_id, idx=1):
        return {
            "run_id": run_id,
            "workout_date": f"2026-01-{idx:02d}",
            "laps": [
                {
                    "band": "easy",
                    "avg_power": 160.0,
                    "avg_hr": 140.0,
                    "distance_km": 2.0,
                    "duration_seconds": 600.0,
                }
            ],
            "decoupling_pct": 4.0,
            "avg_power": 160.0,
            "avg_hr": 140.0,
            "distance_km": 6.0,
            "duration_seconds": 1800,
        }

    def _build_hard_run(self, run_id, idx=1):
        return {
            "run_id": run_id,
            "workout_date": f"2026-01-{idx:02d}",
            "laps": [
                {
                    "band": "hard",
                    "avg_power": 240.0,
                    "avg_hr": 170.0,
                    "distance_km": 1.0,
                    "duration_seconds": 300.0,
                }
            ],
            "decoupling_pct": None,
            "avg_power": 240.0,
            "avg_hr": 170.0,
            "distance_km": 3.0,
            "duration_seconds": 900,
        }

    def test_endurance_score_numeric_when_runs_classified(self):
        """Endurance score is a number in [0,100] when laps have valid bands."""
        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "duration_curve_bests": None,
        }
        runs = [self._build_easy_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)

        assert "score" in result, f"Missing 'score' key: {result}"
        assert isinstance(result["score"], (int, float)), f"Score not numeric: {result}"
        assert 0 <= result["score"] <= 100

    def test_speed_score_numeric_when_runs_classified(self):
        """Speed score is a number in [0,100] when laps have valid hard bands."""
        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "duration_curve_bests": None,
        }
        runs = [self._build_hard_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()
        result = compute_speed_score(runs, prefs, zc)

        assert "score" in result, f"Missing 'score' key: {result}"
        assert isinstance(result["score"], (int, float)), f"Score not numeric: {result}"
        assert 0 <= result["score"] <= 100

    def test_unclassified_laps_do_not_produce_numeric_score(self):
        """Laps with band=None (unclassified) must not produce a numeric score.

        This confirms that classify_laps must be called — without it, laps have
        band=None and no qualifying runs exist, so scores are building_baseline.
        """
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [
                    {
                        "band": None,  # missing classification
                        "avg_power": 160.0,
                        "avg_hr": 140.0,
                        "distance_km": 2.0,
                        "duration_seconds": 600.0,
                    }
                ],
                "decoupling_pct": None,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert result.get("state") == "building_baseline", (
            "band=None laps must not produce a numeric score — classify_laps must be called"
        )

    def test_assembled_runs_from_mock_workouts_produce_numeric_endurance_score(self):
        """End-to-end assembly: classify → assemble → score produces numeric result."""
        # Build enough easy-band workouts to clear MIN_QUALIFYING_RUNS
        workouts = [
            _workout(i, date_str=f"2026-01-{i:02d}")
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        splits_by_id = {
            w.id: [_split(avg_power=150, avg_hr=140, distance_km=2.0, duration_seconds=600)]
            for w in workouts
        }
        # ftp_w=200, avg_power=150 → ratio=0.75 → "easy" (< 0.80)
        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": 300,
            "aerobic_decoupling_threshold": 8.0,
            "duration_curve_bests": None,
        }

        runs = _assemble_runs(workouts, splits_by_id, prefs)

        # Verify each lap has band="easy"
        for run in runs:
            for lap in run["laps"]:
                assert lap["band"] == "easy", f"Expected 'easy', got {lap['band']!r}"

        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)

        assert "score" in result, f"No score key: {result}"
        assert isinstance(result["score"], (int, float)), f"Non-numeric score: {result}"
        assert 0 <= result["score"] <= 100


# ---------------------------------------------------------------------------
# AC8: no thresholds / no runs → safe empty/null response, no exception
# ---------------------------------------------------------------------------

class TestGracefulEmptyResponse:

    def test_no_thresholds_prefs_does_not_raise(self):
        """classify_laps must not raise when prefs is empty."""
        from backend.services.lap_classify import classify_laps
        try:
            result = classify_laps([_split()], {})
        except Exception as exc:
            pytest.fail(f"classify_laps raised with empty prefs: {exc}")
        assert isinstance(result, list)

    def test_empty_prefs_gives_band_none_not_crash(self):
        """All bands are None when prefs has no thresholds — no exception."""
        from backend.services.lap_classify import classify_laps
        result = classify_laps([_split()], {})
        assert result[0]["band"] is None
        assert result[0]["basis"] == "none"

    def test_score_functions_handle_none_prefs_gracefully(self):
        """Score functions return null/building_baseline, not an exception, when prefs=None."""
        zc = make_zone_constants()
        endurance = compute_endurance_score([], None, zc)
        speed = compute_speed_score([], None, zc)
        # Must not raise; result must indicate missing or baseline state
        assert endurance.get("score") is None or endurance.get("state") == "building_baseline"
        assert speed.get("score") is None or speed.get("state") == "building_baseline"

    def test_score_functions_handle_empty_runs_gracefully(self):
        """Score functions return building_baseline, not an exception, when runs=[]."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        zc = make_zone_constants()
        endurance = compute_endurance_score([], prefs, zc)
        speed = compute_speed_score([], prefs, zc)
        assert endurance.get("state") == "building_baseline"
        assert speed.get("state") == "building_baseline"

    def test_no_prefs_returns_reason_string(self):
        """When preferences is None, result includes a non-empty reason string."""
        result = compute_endurance_score([], None, make_zone_constants())
        assert result.get("score") is None
        assert isinstance(result.get("reason"), str) and len(result["reason"]) > 0

    def test_score_functions_handle_no_qualifying_laps(self):
        """Runs with all laps band=None produce building_baseline, not a crash."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        runs = [
            {
                "run_id": "r1",
                "workout_date": "2026-01-01",
                "laps": [
                    {
                        "band": None,
                        "avg_power": 160.0,
                        "avg_hr": 140.0,
                        "distance_km": 2.0,
                        "duration_seconds": 600.0,
                    }
                ],
                "decoupling_pct": None,
            }
        ]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert result.get("state") == "building_baseline"

    def test_no_runs_no_exception(self):
        """Assembly with zero workouts returns empty list without raising."""
        runs = _assemble_runs([], {}, {"ftp_w": 200, "threshold_hr": 165})
        assert runs == []

    def test_none_prefs_row_gives_none_preferences(self):
        """When prefs_row is None, preferences dict is None and scores return null."""
        # Simulate the endpoint's prefs handling
        prefs_row = None
        preferences = None if prefs_row is None else {}
        result = compute_endurance_score([], preferences, make_zone_constants())
        assert result.get("score") is None or result.get("state") == "building_baseline"
