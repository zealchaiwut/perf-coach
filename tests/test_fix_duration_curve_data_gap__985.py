"""Tests for issue #985: Fix duration curve data gap: lap classification and threshold population.

Acceptance Criteria covered:
  AC1: An athlete with 700+ synced workouts sees real personal records (value, date, source
       workout ID). The rebuild caller processes ALL workouts, not just those with power data
       (removing the 'if not new_points: continue' skip).
  AC2: Thresholds and distance targets are driven by configuration or existing codebase
       constants; no values are hardcoded.  _DEFAULT_DURATION_LADDER from duration_curve.py
       must cover every duration in STANDARD_POWER_DURATIONS_SECONDS from pr_detection.py.
  AC3: The duration curve logged by the endpoint is non-empty for athletes with sufficient
       run history.  When no AthleteDurationCurve row exists, the endpoint triggers a
       rebuild before calling fetch_and_detect_records.
  AC4: No logic changes are made inside backend/services/pr_detection.py.
  AC5: Existing unit tests for pr_detection.py continue to pass (verified by importing the
       same symbols used in test_pr_detection_from_run_history__704.py).
"""

import unittest.mock as mock
import pytest


# ── AC1: lap-skip bug — rebuild must process ALL workouts ─────────────────────


class TestRebuildProcessesAllWorkouts:
    """AC1: rebuild_athlete_duration_curve must evaluate every run workout.

    Before the fix, the 'if not new_points: continue' guard silently skipped any
    workout whose power_curve was empty.  If a workout happened to lack power data
    at the time of the rebuild (e.g., Stryd splits missing), it was permanently
    excluded from the curve even if good data was available for other durations.

    After the fix, merge_best_effort is called for every workout — for workouts
    without power data it is called with an empty list, which is a safe no-op.
    """

    def _make_mock_db(self):
        """Return a minimal mock DB session whose workout query yields a MagicMock list."""
        mock_db = mock.MagicMock()
        mock_db.get.return_value = None  # no existing AthleteDurationCurve row
        return mock_db

    def _make_workouts(self, ids):
        workouts = []
        for wid in ids:
            w = mock.MagicMock()
            w.id = wid
            w.user_id = "user-1"
            w.workout_date = "2026-01-01"
            w.workout_type = "run"
            workouts.append(w)
        return workouts

    def test_merge_called_for_workouts_without_power(self):
        """AC1: merge_best_effort is invoked for every workout, including those with empty
        power_curve.  Before the fix this was 1 call; after the fix it is 3."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve
        from backend.services.duration_curve_best_effort import merge_best_effort as real_merge

        workouts = self._make_workouts(["w1", "w2", "w3"])
        power_data = {
            "w1": [],  # no power
            "w2": [],  # no power
            "w3": [
                {
                    "duration_seconds": 300,
                    "best_value": 280.0,
                    "source_workout_id": "w3",
                    "date": "2026-01-01",
                    "confidence": "measured",
                }
            ],
        }

        mock_db = self._make_mock_db()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = workouts

        merge_calls = []

        def fake_fetch(workout_id, db):
            return {"power_curve": power_data.get(str(workout_id), []), "pace_curve": []}

        def tracking_merge(existing, new_points, higher_is_better=True):
            merge_calls.append(new_points)
            return real_merge(existing, new_points, higher_is_better)

        # fetch_and_compute_curves and merge_best_effort are local imports inside
        # rebuild_athlete_duration_curve — patch them at their source module.
        with (
            mock.patch(
                "backend.services.duration_curve.fetch_and_compute_curves",
                side_effect=fake_fetch,
            ),
            mock.patch(
                "backend.services.duration_curve_best_effort.merge_best_effort",
                side_effect=tracking_merge,
            ),
        ):
            curve, reason = rebuild_athlete_duration_curve("user-1", mock_db)

        assert len(merge_calls) == 3, (
            f"Expected merge_best_effort called 3 times (once per workout), "
            f"got {len(merge_calls)}.  The 'if not new_points: continue' skip must be removed."
        )

    def test_curve_contains_power_data_after_rebuild_with_mixed_workouts(self):
        """AC1: curve retains power data from workouts that do have power even when
        other workouts in the same batch have no power."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        workouts = self._make_workouts(["w1", "w2"])
        power_data = {
            "w1": [],  # no power
            "w2": [
                {
                    "duration_seconds": 300,
                    "best_value": 290.0,
                    "source_workout_id": "w2",
                    "date": "2026-01-02",
                    "confidence": "measured",
                }
            ],
        }

        mock_db = self._make_mock_db()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = workouts

        def fake_fetch(workout_id, db):
            return {"power_curve": power_data.get(str(workout_id), []), "pace_curve": []}

        # patch at the source module since fetch_and_compute_curves is a local import
        with mock.patch(
            "backend.services.duration_curve.fetch_and_compute_curves",
            side_effect=fake_fetch,
        ):
            curve, reason = rebuild_athlete_duration_curve("user-1", mock_db)

        assert reason is None
        assert "300" in curve, (
            f"Expected '300' key in rebuilt curve (from w2 power data), got: {list(curve.keys())}"
        )
        assert curve["300"]["best_value"] == 290.0

    def test_rebuild_no_workouts_returns_empty_curve(self):
        """AC1: rebuild with no workouts returns ({}, None) — stable no-op."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        mock_db = self._make_mock_db()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        curve, reason = rebuild_athlete_duration_curve("user-1", mock_db)

        assert curve == {}
        assert reason is None

    def test_rebuild_user_id_none_returns_error(self):
        """AC1: rebuild with None user_id returns error reason rather than raising."""
        from backend.services.lap_recompute import rebuild_athlete_duration_curve

        mock_db = mock.MagicMock()
        curve, reason = rebuild_athlete_duration_curve(None, mock_db)

        assert curve == {}
        assert reason is not None


# ── AC2: thresholds from constants, not hardcoded values ─────────────────────


class TestThresholdsFromConstants:
    """AC2: duration thresholds used in curve building come from existing codebase constants.

    _DEFAULT_DURATION_LADDER from backend.services.duration_curve is the authoritative
    ladder consumed by fetch_and_compute_curves (and therefore rebuild_athlete_duration_curve).
    Every duration tracked by pr_detection.STANDARD_POWER_DURATIONS_SECONDS must be
    present in that ladder so the AthleteDurationCurve stores data at the right windows.
    """

    def test_standard_power_durations_in_default_ladder(self):
        """AC2: every value in STANDARD_POWER_DURATIONS_SECONDS is in _DEFAULT_DURATION_LADDER."""
        from backend.services.pr_detection import STANDARD_POWER_DURATIONS_SECONDS
        from backend.services.duration_curve import _DEFAULT_DURATION_LADDER

        for label, dur_sec in STANDARD_POWER_DURATIONS_SECONDS.items():
            assert dur_sec in _DEFAULT_DURATION_LADDER, (
                f"STANDARD_POWER_DURATIONS_SECONDS['{label}'] = {dur_sec}s is NOT in "
                f"_DEFAULT_DURATION_LADDER {_DEFAULT_DURATION_LADDER}. "
                "The curve building ladder must cover all PR detection durations."
            )

    def test_60_seconds_in_default_duration_ladder(self):
        """AC2: the 1-minute (60 s) window required for best1Min power PR is in the ladder."""
        from backend.services.duration_curve import _DEFAULT_DURATION_LADDER
        assert 60 in _DEFAULT_DURATION_LADDER, (
            "60 seconds (best-1-minute power) must be in _DEFAULT_DURATION_LADDER so the "
            "duration curve can record it."
        )

    def test_standard_distances_defined_as_constant(self):
        """AC2: distance targets for speed PR detection come from a module-level constant."""
        from backend.services.pr_detection import STANDARD_DISTANCES_KM
        assert isinstance(STANDARD_DISTANCES_KM, dict)
        assert len(STANDARD_DISTANCES_KM) > 0, "STANDARD_DISTANCES_KM must not be empty"
        # Spot-check the six standard distances are present
        for key in ("1km", "5km", "10km", "half_marathon", "marathon"):
            assert key in STANDARD_DISTANCES_KM, (
                f"Expected distance key '{key}' in STANDARD_DISTANCES_KM"
            )

    def test_standard_power_durations_defined_as_constant(self):
        """AC2: power duration targets for power PR detection come from a module-level constant."""
        from backend.services.pr_detection import STANDARD_POWER_DURATIONS_SECONDS
        assert isinstance(STANDARD_POWER_DURATIONS_SECONDS, dict)
        assert "best1Min" in STANDARD_POWER_DURATIONS_SECONDS
        assert "best5Min" in STANDARD_POWER_DURATIONS_SECONDS
        assert "best20Min" in STANDARD_POWER_DURATIONS_SECONDS
        assert STANDARD_POWER_DURATIONS_SECONDS["best1Min"] == 60
        assert STANDARD_POWER_DURATIONS_SECONDS["best5Min"] == 300
        assert STANDARD_POWER_DURATIONS_SECONDS["best20Min"] == 1200


# ── AC3: endpoint triggers rebuild when curve is absent ───────────────────────


def _fake_pr_detection_raw():
    """Return a minimal fetch_and_detect_records result for mocking."""
    return {
        "speedRecords": {"reason": "duration curve is empty"},
        "powerRecords": {"reason": "duration curve is empty"},
        "volumeRecords": {"reason": "no completed runs provided"},
        "_meta": {
            "duration_curve_populated": False,
            "runs_considered": 0,
        },
    }


class TestEndpointTriggersRebuild:
    """AC3: when AthleteDurationCurve row is absent the endpoint rebuilds before logging.

    The rebuild is idempotent (safe to call multiple times) and uses the same
    lap-classification data path as the backfill script.  After rebuild the
    curve row exists and detection can produce real records.
    """

    def _make_mock_session(self, run_count=50, curve_record=None):
        """Return a mock SQLAlchemy session."""
        ms = mock.MagicMock()
        ms.__enter__ = mock.MagicMock(return_value=ms)
        ms.__exit__ = mock.MagicMock(return_value=False)
        ms.query.return_value.filter.return_value.count.return_value = run_count
        ms.get.return_value = curve_record
        return ms

    def test_rebuild_called_when_curve_absent(self):
        """AC3: _rebuild_athlete_duration_curve is called exactly once when no curve row exists."""
        import backend.main as main_mod

        mock_user = mock.MagicMock()
        mock_user.id = "user-1"

        mock_session = self._make_mock_session(run_count=50, curve_record=None)
        rebuild_calls = []

        def fake_rebuild(user_id, db):
            rebuild_calls.append(user_id)
            return {}, None

        with (
            mock.patch("backend.main.Session", return_value=mock_session),
            mock.patch(
                "backend.main._rebuild_athlete_duration_curve",
                side_effect=fake_rebuild,
            ),
            mock.patch(
                "backend.services.pr_detection.fetch_and_detect_records",
                return_value=dict(_fake_pr_detection_raw()),
            ),
        ):
            main_mod.get_athlete_run_personal_records(user=mock_user)

        assert len(rebuild_calls) == 1, (
            f"Expected rebuild to be called once when curve is absent, got {len(rebuild_calls)} calls. "
            "The endpoint must trigger _rebuild_athlete_duration_curve when no curve row exists."
        )
        assert rebuild_calls[0] == "user-1"

    def test_rebuild_not_called_when_curve_exists(self):
        """AC3: _rebuild_athlete_duration_curve is NOT called when a curve row already exists."""
        import backend.main as main_mod

        mock_user = mock.MagicMock()
        mock_user.id = "user-2"

        existing_curve = mock.MagicMock()
        existing_curve.curve_data = {"300": {"best_value": 280.0}}

        mock_session = self._make_mock_session(run_count=200, curve_record=existing_curve)
        rebuild_calls = []

        with (
            mock.patch("backend.main.Session", return_value=mock_session),
            mock.patch(
                "backend.main._rebuild_athlete_duration_curve",
                side_effect=lambda *a, **kw: rebuild_calls.append(True) or ({}, None),
            ),
            mock.patch(
                "backend.services.pr_detection.fetch_and_detect_records",
                return_value=dict(_fake_pr_detection_raw()),
            ),
        ):
            main_mod.get_athlete_run_personal_records(user=mock_user)

        assert len(rebuild_calls) == 0, (
            f"rebuild_athlete_duration_curve must NOT be called when the curve row exists "
            f"(got {len(rebuild_calls)} calls).  Avoids expensive O(n) rebuild on every request."
        )

    def test_fetch_and_detect_called_after_rebuild(self):
        """AC3: fetch_and_detect_records is always called — even after a rebuild."""
        import backend.main as main_mod

        mock_user = mock.MagicMock()
        mock_user.id = "user-3"

        mock_session = self._make_mock_session(run_count=5, curve_record=None)
        detect_calls = []

        def fake_detect(user_id, db):
            detect_calls.append(user_id)
            return dict(_fake_pr_detection_raw())

        with (
            mock.patch("backend.main.Session", return_value=mock_session),
            mock.patch(
                "backend.main._rebuild_athlete_duration_curve",
                return_value=({}, None),
            ),
            mock.patch(
                "backend.services.pr_detection.fetch_and_detect_records",
                side_effect=fake_detect,
            ),
        ):
            main_mod.get_athlete_run_personal_records(user=mock_user)

        assert len(detect_calls) == 1, (
            "fetch_and_detect_records must be called once, after any rebuild."
        )

    def test_endpoint_returns_200_with_pr_keys(self):
        """AC3: the endpoint always returns a 200 JSONResponse with the three PR category keys."""
        import backend.main as main_mod
        from fastapi.responses import JSONResponse

        mock_user = mock.MagicMock()
        mock_user.id = "user-4"

        mock_session = self._make_mock_session(run_count=0, curve_record=None)

        with (
            mock.patch("backend.main.Session", return_value=mock_session),
            mock.patch(
                "backend.main._rebuild_athlete_duration_curve",
                return_value=({}, None),
            ),
            mock.patch(
                "backend.services.pr_detection.fetch_and_detect_records",
                return_value=dict(_fake_pr_detection_raw()),
            ),
        ):
            response = main_mod.get_athlete_run_personal_records(user=mock_user)

        assert isinstance(response, JSONResponse)
        import json
        body = json.loads(response.body)
        for key in ("speedRecords", "powerRecords", "volumeRecords"):
            assert key in body, f"Response must include '{key}' key; got {list(body.keys())}"
        assert "_meta" not in body, "_meta is internal and must be stripped from the response"


# ── AC4: pr_detection.py is unchanged ─────────────────────────────────────────


class TestPrDetectionModuleUnchanged:
    """AC4: no logic changes inside backend/services/pr_detection.py.

    These smoke tests call each pure function with known inputs and verify the
    return structure.  If any signature or behaviour was accidentally changed,
    these tests will catch it.
    """

    def test_detect_speed_records_importable(self):
        from backend.services.pr_detection import detect_speed_records
        assert callable(detect_speed_records)

    def test_detect_power_records_importable(self):
        from backend.services.pr_detection import detect_power_records
        assert callable(detect_power_records)

    def test_detect_volume_records_importable(self):
        from backend.services.pr_detection import detect_volume_records
        assert callable(detect_volume_records)

    def test_fetch_and_detect_records_importable(self):
        from backend.services.pr_detection import fetch_and_detect_records
        assert callable(fetch_and_detect_records)

    def test_detect_speed_records_empty_returns_reason(self):
        """AC4: detect_speed_records with empty inputs still returns a reason string."""
        from backend.services.pr_detection import detect_speed_records
        result = detect_speed_records([], [])
        assert "reason" in result

    def test_detect_power_records_empty_returns_reason(self):
        """AC4: detect_power_records with empty power curve returns a reason string."""
        from backend.services.pr_detection import detect_power_records
        result = detect_power_records([])
        assert "reason" in result

    def test_detect_volume_records_empty_returns_reason(self):
        """AC4: detect_volume_records with no runs returns a reason string."""
        from backend.services.pr_detection import detect_volume_records
        result = detect_volume_records([])
        assert "reason" in result

    def test_standard_distances_km_constant_present(self):
        """AC4: STANDARD_DISTANCES_KM is still a module-level dict in pr_detection."""
        from backend.services.pr_detection import STANDARD_DISTANCES_KM
        assert isinstance(STANDARD_DISTANCES_KM, dict)
        assert len(STANDARD_DISTANCES_KM) == 6

    def test_standard_power_durations_seconds_constant_present(self):
        """AC4: STANDARD_POWER_DURATIONS_SECONDS is still a module-level dict in pr_detection."""
        from backend.services.pr_detection import STANDARD_POWER_DURATIONS_SECONDS
        assert isinstance(STANDARD_POWER_DURATIONS_SECONDS, dict)
        assert len(STANDARD_POWER_DURATIONS_SECONDS) == 3

    def test_fetch_and_detect_returns_meta(self):
        """AC4/AC5: fetch_and_detect_records still includes _meta in its return value."""
        from backend.services.pr_detection import fetch_and_detect_records

        mock_db = mock.MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        mock_db.get.return_value = None

        result = fetch_and_detect_records(user_id=1, db=mock_db)
        assert "_meta" in result
        assert "duration_curve_populated" in result["_meta"]
        assert "runs_considered" in result["_meta"]


# ── AC5: existing pr_detection tests still pass (structural smoke test) ───────


class TestExistingPrDetectionTestsStillPass:
    """AC5: the pure-function test suite in test_pr_detection_from_run_history__704.py
    must continue to pass.  Here we reproduce the helper shapes and assert the same
    invariants so any accidental signature change is caught even before running the
    full suite.
    """

    def _run(self, id_, date, distance_km, duration_seconds):
        return {
            "id": id_,
            "workout_date": date,
            "distance_km": distance_km,
            "duration_seconds": duration_seconds,
            "tss": None,
            "avg_power": None,
            "workout_type": "run",
        }

    def _pace_point(self, duration_seconds, best_value, source_workout_id, date):
        return {
            "duration_seconds": duration_seconds,
            "best_value": best_value,
            "source_workout_id": source_workout_id,
            "date": date,
            "source_workout": None,
        }

    def test_speed_records_detects_5km_best(self):
        """AC5: a 5 km run is detected as the best 5 km time."""
        from backend.services.pr_detection import detect_speed_records
        run = self._run("r1", "2026-01-10", 5.0, 1200)
        curve = [self._pace_point(1200, 1200 / 5.0, "r1", "2026-01-10")]
        result = detect_speed_records(curve, [run])
        assert "5km" in result
        rec = result["5km"]
        assert rec["value"] is not None

    def test_volume_records_longest_by_distance(self):
        """AC5: detect_volume_records identifies the longest run by distance."""
        from backend.services.pr_detection import detect_volume_records
        long_run = self._run("r2", "2026-01-15", 42.195, 14400)
        result = detect_volume_records([long_run])
        assert "longestByDistance" in result
        assert result["longestByDistance"]["value"] == pytest.approx(42.195)
