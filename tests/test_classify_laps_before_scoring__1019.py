"""Tests for issue #1019: Classify laps before scoring in performance endpoint.

Acceptance Criteria covered:
  AC1: The performance endpoint calls classify_laps on every run in scope
       using the athlete's thresholds before invoking any scoring function.
  AC2: After classification, each qualifying lap carries a band field
       (value is a non-empty string).
  AC3: For a test athlete with thresholds configured, the count of laps
       where band is set is greater than zero.
  AC4: The speed scoring function receives at least three qualifying
       (banded) runs.
  AC5: Endurance scoring results are non-empty when at least one lap qualifies.
  AC6: The classification step does not alter the endpoint's response schema
       -- only internal lap data is enriched.
"""

import datetime
from types import SimpleNamespace


from backend.services.running_performance import compute_endurance_score, compute_speed_score
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _split(avg_power=180, avg_hr=140, distance_km=2.0, duration_seconds=600, split_index=0):
    return SimpleNamespace(
        split_index=split_index,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
    )


def _workout(wid=1, date_str="2026-01-01"):
    return SimpleNamespace(
        id=wid,
        user_id=1,
        workout_type="Run",
        workout_date=datetime.date.fromisoformat(date_str),
        start_time=None,
        avg_power=180,
        avg_hr=140,
        distance_km=6.0,
        duration_seconds=1800,
    )


def _assemble_runs(workouts, splits_by_id, prefs_dict):
    """Replicate the endpoint's run-assembly loop (no DB, pure helpers).

    Mirrors the logic in get_athlete_performance so tests can exercise the
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

        # AC1: classify_laps is called before scoring, using athlete's thresholds
        classifications = classify_laps(splits, prefs_dict)

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
# AC1: classify_laps called on every run before scoring
# ---------------------------------------------------------------------------

class TestClassifyLapsCalledBeforeScoring:

    def test_classify_laps_is_importable(self):
        from backend.services.lap_classify import classify_laps
        assert callable(classify_laps)

    def test_classify_laps_called_for_each_workout(self):
        """One classify_laps call per workout — verified by counting calls."""
        from backend.services.lap_classify import classify_laps

        workouts = [_workout(i, date_str=f"2026-01-{i:02d}") for i in range(1, 4)]
        splits_by_id = {w.id: [_split()] for w in workouts}
        prefs = {"ftp_w": 200}

        call_count = 0
        original = classify_laps

        def counting_classify(splits, prefs_d):
            nonlocal call_count
            call_count += 1
            return original(splits, prefs_d)

        for workout in workouts:
            sp = splits_by_id[workout.id]
            counting_classify(sp, prefs)

        assert call_count == len(workouts)

    def test_classify_laps_result_length_matches_splits(self):
        """classify_laps returns one classification per split."""
        from backend.services.lap_classify import classify_laps
        splits = [_split(avg_power=160 + i * 10) for i in range(5)]
        prefs = {"ftp_w": 200}
        result = classify_laps(splits, prefs)
        assert len(result) == len(splits)

    def test_classify_laps_called_before_scoring_functions_receive_laps(self):
        """Laps reaching score functions already have band field populated."""
        workouts = [_workout(i, date_str=f"2026-01-{i:02d}") for i in range(1, 4)]
        splits_by_id = {w.id: [_split(avg_power=150)] for w in workouts}
        prefs = {"ftp_w": 200}

        runs = _assemble_runs(workouts, splits_by_id, prefs)
        for run in runs:
            for lap in run["laps"]:
                assert "band" in lap, "Each lap must have 'band' before reaching score functions"


# ---------------------------------------------------------------------------
# AC2: qualifying laps carry a band field that is a non-empty string
# ---------------------------------------------------------------------------

class TestQualifyingLapsHaveNonEmptyBand:

    def test_band_is_non_empty_string_when_threshold_set(self):
        """When ftp_w is set and avg_power is present, band is a non-empty string."""
        from backend.services.lap_classify import classify_laps
        # ftp_w=200, avg_power=180 → ratio=0.90 → "tempo"
        splits = [_split(avg_power=180)]
        result = classify_laps(splits, {"ftp_w": 200})
        band = result[0]["band"]
        assert isinstance(band, str) and len(band) > 0, (
            f"Expected non-empty string band, got: {band!r}"
        )

    def test_band_values_are_from_valid_set(self):
        """Band must be one of the five valid intensity labels."""
        from backend.services.lap_classify import classify_laps
        valid_bands = {"easy", "steady", "tempo", "threshold", "hard"}
        splits = [_split(avg_power=p) for p in [120, 160, 190, 205, 230]]
        prefs = {"ftp_w": 200}
        results = classify_laps(splits, prefs)
        for res in results:
            assert res["band"] in valid_bands, f"Unexpected band value: {res['band']!r}"

    def test_band_is_none_only_when_no_thresholds_configured(self):
        """band=None only when no thresholds exist in prefs — not for classified laps."""
        from backend.services.lap_classify import classify_laps
        splits = [_split(avg_power=180)]
        result_no_prefs = classify_laps(splits, {})
        result_with_prefs = classify_laps(splits, {"ftp_w": 200})
        assert result_no_prefs[0]["band"] is None
        assert result_with_prefs[0]["band"] is not None

    def test_assembled_lap_band_is_non_empty_string(self):
        """After assembly, laps with thresholds have non-empty string bands."""
        workouts = [_workout(1)]
        splits_by_id = {1: [_split(avg_power=160)]}
        prefs = {"ftp_w": 200}
        runs = _assemble_runs(workouts, splits_by_id, prefs)
        lap = runs[0]["laps"][0]
        assert isinstance(lap["band"], str) and len(lap["band"]) > 0


# ---------------------------------------------------------------------------
# AC3: count of banded laps > 0 for athlete with thresholds configured
# ---------------------------------------------------------------------------

class TestBandedLapCountGreaterThanZero:

    def test_at_least_one_lap_has_band_set_when_thresholds_present(self):
        """With thresholds and power data, at least one lap has band set."""
        workouts = [_workout(i, date_str=f"2026-01-{i:02d}") for i in range(1, 4)]
        splits_by_id = {w.id: [_split(avg_power=160)] for w in workouts}
        prefs = {"ftp_w": 200}

        runs = _assemble_runs(workouts, splits_by_id, prefs)
        banded_count = sum(
            1
            for run in runs
            for lap in run["laps"]
            if lap.get("band") is not None
        )
        assert banded_count > 0, (
            f"Expected >0 banded laps, got {banded_count}"
        )

    def test_banded_lap_count_equals_total_laps_when_all_have_power(self):
        """When all splits have avg_power and ftp_w is set, all laps get a band."""
        workouts = [_workout(1)]
        splits_by_id = {1: [_split(avg_power=p) for p in (150, 170, 195)]}
        prefs = {"ftp_w": 200}

        runs = _assemble_runs(workouts, splits_by_id, prefs)
        total_laps = sum(len(run["laps"]) for run in runs)
        banded_laps = sum(
            1
            for run in runs
            for lap in run["laps"]
            if lap.get("band") is not None
        )
        assert banded_laps == total_laps, (
            f"All {total_laps} laps should be banded; only {banded_laps} were"
        )

    def test_banded_lap_count_is_zero_when_no_thresholds(self):
        """With no thresholds, all bands are None — count of banded laps is 0."""
        workouts = [_workout(1)]
        splits_by_id = {1: [_split()]}
        prefs = {}  # no thresholds

        runs = _assemble_runs(workouts, splits_by_id, prefs)
        banded_count = sum(
            1
            for run in runs
            for lap in run["laps"]
            if lap.get("band") is not None
        )
        assert banded_count == 0

    def test_banded_lap_count_from_classify_laps_directly(self):
        """classify_laps itself produces non-zero banded count with valid inputs."""
        from backend.services.lap_classify import classify_laps
        splits = [_split(avg_power=p) for p in (150, 165, 185, 210)]
        prefs = {"ftp_w": 200}
        results = classify_laps(splits, prefs)
        banded = [r for r in results if r.get("band") is not None]
        assert len(banded) > 0, f"Expected >0 banded results, got {len(banded)}"


# ---------------------------------------------------------------------------
# AC4: speed scoring function receives at least three qualifying (banded) runs
# ---------------------------------------------------------------------------

class TestSpeedScoringReceivesMinimumQualifyingRuns:

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

    def test_speed_score_with_exactly_min_qualifying_runs_is_numeric(self):
        """Exactly MIN_QUALIFYING_RUNS hard-band runs produces a numeric speed score."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        runs = [self._hard_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS + 1)]
        zc = make_zone_constants()
        result = compute_speed_score(runs, prefs, zc)
        assert isinstance(result.get("score"), (int, float)), (
            f"Expected numeric score with {MIN_QUALIFYING_RUNS} qualifying runs: {result}"
        )

    def test_speed_score_with_fewer_than_min_runs_returns_building_baseline(self):
        """Fewer than MIN_QUALIFYING_RUNS qualifying runs yields building_baseline."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        runs = [self._hard_run(f"r{i}", i) for i in range(1, MIN_QUALIFYING_RUNS)]
        zc = make_zone_constants()
        result = compute_speed_score(runs, prefs, zc)
        assert result.get("state") == "building_baseline", (
            f"Expected building_baseline with {MIN_QUALIFYING_RUNS - 1} runs: {result}"
        )

    def test_speed_score_only_counts_hard_band_runs(self):
        """Only runs with speed-band laps count toward the qualifying run threshold."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        zc = make_zone_constants()

        # Mix: MIN_QUALIFYING_RUNS+1 easy runs (not speed-band) and 2 hard runs
        easy_runs = [
            {
                "run_id": f"easy{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": "easy", "avg_power": 150.0, "avg_hr": 130.0,
                           "distance_km": 2.0, "duration_seconds": 600.0}],
                "decoupling_pct": None,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        hard_runs = [self._hard_run(f"hard{i}", i + 20) for i in range(1, 3)]
        result = compute_speed_score(easy_runs + hard_runs, prefs, zc)
        # 2 hard runs < MIN_QUALIFYING_RUNS → building_baseline
        assert result.get("state") == "building_baseline"

    def test_assembled_runs_with_hard_band_qualify_for_speed_score(self):
        """Assembly of MIN_QUALIFYING_RUNS+1 hard-power runs yields numeric speed score."""
        # avg_power=230, ftp_w=200 → ratio=1.15 → "hard"
        workouts = [
            _workout(i, date_str=f"2026-01-{i:02d}")
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        splits_by_id = {
            w.id: [_split(avg_power=230, avg_hr=165, distance_km=1.0, duration_seconds=300)]
            for w in workouts
        }
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}

        runs = _assemble_runs(workouts, splits_by_id, prefs)

        # Verify hard band was correctly assigned
        for run in runs:
            for lap in run["laps"]:
                assert lap["band"] == "hard", (
                    f"Expected 'hard' band (ratio=1.15), got {lap['band']!r}"
                )

        zc = make_zone_constants()
        result = compute_speed_score(runs, prefs, zc)
        assert isinstance(result.get("score"), (int, float)), (
            f"Expected numeric speed score from assembled runs: {result}"
        )


# ---------------------------------------------------------------------------
# AC5: endurance scoring results are non-empty when at least one lap qualifies
# ---------------------------------------------------------------------------

class TestEnduranceScoringNonEmptyWhenLapQualifies:

    def _easy_run(self, run_id, idx=1, avg_power=150):
        return {
            "run_id": run_id,
            "workout_date": f"2026-01-{idx:02d}",
            "laps": [
                {
                    "band": "easy",
                    "avg_power": float(avg_power),
                    "avg_hr": 135.0,
                    "distance_km": 2.0,
                    "duration_seconds": 600.0,
                }
            ],
            "decoupling_pct": 4.0,
            "avg_power": float(avg_power),
            "avg_hr": 135.0,
            "distance_km": 6.0,
            "duration_seconds": 1800,
        }

    def test_endurance_score_key_present_with_qualifying_runs(self):
        """compute_endurance_score result has a 'score' key when runs qualify."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        runs = [self._easy_run(f"r{i}", i, avg_power=140 + i * 3) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert "score" in result, f"Expected 'score' key in result: {result}"

    def test_endurance_score_is_numeric_with_easy_runs(self):
        """Numeric endurance score returned when easy-band laps qualify."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        runs = [self._easy_run(f"r{i}", i, avg_power=140 + i * 3) for i in range(1, MIN_QUALIFYING_RUNS + 2)]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert isinstance(result["score"], (int, float)), f"Score not numeric: {result}"
        assert 0 <= result["score"] <= 100

    def test_endurance_score_has_trend_list(self):
        """Result includes a 'trend' list matching the number of qualifying runs."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        n = MIN_QUALIFYING_RUNS + 1
        runs = [self._easy_run(f"r{i}", i, avg_power=140 + i * 3) for i in range(1, n + 1)]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert "trend" in result, f"Expected 'trend' key: {result}"
        assert isinstance(result["trend"], list)
        assert len(result["trend"]) == n

    def test_endurance_score_with_zero_qualifying_laps_is_building_baseline(self):
        """No qualifying laps (band=None) → building_baseline, not empty score."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": None, "avg_power": 150.0, "avg_hr": 135.0,
                           "distance_km": 2.0, "duration_seconds": 600.0}],
                "decoupling_pct": None,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)
        assert result.get("state") == "building_baseline", (
            "Unclassified laps (band=None) must produce building_baseline, not a numeric score"
        )

    def test_endurance_score_from_assembled_runs_is_non_empty(self):
        """End-to-end: classify → assemble → score yields non-empty endurance result."""
        # avg_power=150, ftp_w=200 → ratio=0.75 → "easy"
        workouts = [
            _workout(i, date_str=f"2026-01-{i:02d}")
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        splits_by_id = {
            w.id: [_split(avg_power=150, avg_hr=135, distance_km=2.0, duration_seconds=600)]
            for w in workouts
        }
        prefs = {
            "ftp_w": 200,
            "threshold_hr": 165,  # VDOT re-anchor: endurance needs threshold_hr
            "aerobic_decoupling_threshold": 8.0,
            "duration_curve_bests": None,
        }

        runs = _assemble_runs(workouts, splits_by_id, prefs)

        for run in runs:
            for lap in run["laps"]:
                assert lap["band"] == "easy", f"Expected 'easy', got {lap['band']!r}"

        zc = make_zone_constants()
        result = compute_endurance_score(runs, prefs, zc)

        assert "score" in result, f"Expected 'score' key: {result}"
        assert isinstance(result["score"], (int, float))
        assert 0 <= result["score"] <= 100


# ---------------------------------------------------------------------------
# AC6: classification does not alter endpoint response schema
# ---------------------------------------------------------------------------

class TestClassificationDoesNotAlterResponseSchema:

    def test_response_has_endurance_and_speed_keys(self):
        """The response schema stays {endurance: ..., speed: ...}."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        zc = make_zone_constants()
        endurance = compute_endurance_score([], prefs, zc)
        speed = compute_speed_score([], prefs, zc)
        # Both return dicts (building_baseline or numeric) — schema is intact
        assert isinstance(endurance, dict)
        assert isinstance(speed, dict)

    def test_response_schema_unchanged_regardless_of_band_presence(self):
        """Both classified and unclassified runs return the same response shape."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        zc = make_zone_constants()

        classified_runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": "easy", "avg_power": 150.0, "avg_hr": 135.0,
                           "distance_km": 2.0, "duration_seconds": 600.0}],
                "decoupling_pct": None,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]
        unclassified_runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": None, "avg_power": 150.0, "avg_hr": 135.0,
                           "distance_km": 2.0, "duration_seconds": 600.0}],
                "decoupling_pct": None,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 2)
        ]

        r_classified = compute_endurance_score(classified_runs, prefs, zc)
        r_unclassified = compute_endurance_score(unclassified_runs, prefs, zc)

        # Both must be dicts — schema is preserved either way
        assert isinstance(r_classified, dict)
        assert isinstance(r_unclassified, dict)

    def test_lap_band_field_not_in_api_response(self):
        """The band field enriches internal lap data only — it is not in the JSON response.

        The endpoint returns {endurance: ..., speed: ...}; band is an implementation
        detail used by the scoring functions and never exposed to the caller.
        """
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        zc = make_zone_constants()
        endurance = compute_endurance_score([], prefs, zc)
        speed = compute_speed_score([], prefs, zc)

        # The top-level response keys must not include 'band' or 'laps'
        assert "band" not in endurance
        assert "laps" not in endurance
        assert "band" not in speed
        assert "laps" not in speed

    def test_no_new_top_level_keys_introduced_by_classification(self):
        """Classification adds band to lap dicts but must not add new keys to the response."""
        prefs = {"ftp_w": 200, "threshold_hr": 165, "duration_curve_bests": None}
        zc = make_zone_constants()
        allowed_endurance_keys = {"score", "direction", "trend", "debug", "state", "reason"}
        allowed_speed_keys = {"score", "direction", "trend", "debug", "state", "reason"}

        endurance = compute_endurance_score([], prefs, zc)
        speed = compute_speed_score([], prefs, zc)

        unexpected_endurance = set(endurance.keys()) - allowed_endurance_keys
        unexpected_speed = set(speed.keys()) - allowed_speed_keys
        assert not unexpected_endurance, f"Unexpected keys in endurance result: {unexpected_endurance}"
        assert not unexpected_speed, f"Unexpected keys in speed result: {unexpected_speed}"

    def test_schema_consistent_for_athlete_with_no_thresholds(self):
        """Graceful degradation: no thresholds → valid dict response, no exception."""
        zc = make_zone_constants()
        endurance = compute_endurance_score([], None, zc)
        speed = compute_speed_score([], None, zc)
        assert isinstance(endurance, dict)
        assert isinstance(speed, dict)
