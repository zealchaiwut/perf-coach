"""TDD tests for issue #1656: isStravaWorkout must check strava_activity_pk.

Background: in #1603, the inline `has_strava` computation in `_workoutDictToEntry`
was refactored from:
    source.indexOf("strava") !== -1 || !!w.strava_activity_pk
to:
    isStravaWorkout(w)

But isStravaWorkout only checks `source` and `strava_activity_url`, not
`strava_activity_pk`. A Strava-backed workout with a null strava_activity_url
and a source that doesn't contain "strava" now evaluates to has_strava=false,
hiding the Strava badge.

Additionally, the list API (_workout_list_dict) does NOT expose strava_activity_pk
in its response, so even adding the pk check to isStravaWorkout wouldn't help
for the list-view code path. The fix must also fall back to the backend-provided
w.has_strava field.

Acceptance criteria:
  AC1 - isStravaWorkout in training-log.js checks strava_activity_pk so
        pk-only detail-view workouts keep their Strava badge
  AC2 - _workoutDictToEntry falls back to w.has_strava (from API) so
        list-view pk-only workouts also keep their badge (since the list
        response omits strava_activity_pk)
  AC3 - GET /api/workouts/{id} (detail endpoint) exposes strava_activity_pk
        so the JS can use it
  AC4 - has_stryd and has_strava use consistent field logic (both check pk)
"""
import pathlib
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app

_ROOT = pathlib.Path(__file__).parent.parent
_LOG_JS = (_ROOT / "frontend" / "js" / "training-log.js").read_text()

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000016560000")


def _make_client():
    u = MagicMock()
    u.id = _USER_ID
    u.name = "test-1656"
    u.is_admin = True
    u.is_active = True

    async def _resolve():
        return u

    app.dependency_overrides[resolve_user] = _resolve
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


# ── AC1: isStravaWorkout checks strava_activity_pk ──────────────────────────

class TestIsStravaWorkoutIncludesPkCheck:
    """AC1: The isStravaWorkout function must reference strava_activity_pk."""

    def _get_fn_body(self):
        fn_start = _LOG_JS.find("function isStravaWorkout(")
        assert fn_start != -1, "isStravaWorkout function not found in training-log.js"
        # Walk forward to find the matching closing brace
        depth = 0
        fn_end = fn_start
        for i in range(fn_start, len(_LOG_JS)):
            if _LOG_JS[i] == "{":
                depth += 1
            elif _LOG_JS[i] == "}":
                depth -= 1
                if depth == 0:
                    fn_end = i
                    break
        return _LOG_JS[fn_start : fn_end + 1]

    def test_is_strava_workout_checks_strava_activity_pk(self):
        """isStravaWorkout must include strava_activity_pk so pk-only Strava
        workouts (null strava_activity_url, non-Strava source) return true."""
        fn_body = self._get_fn_body()
        assert "strava_activity_pk" in fn_body, (
            "isStravaWorkout must check strava_activity_pk. A workout with "
            "strava_activity_pk set but null strava_activity_url and non-Strava "
            "source would otherwise evaluate to false."
        )

    def test_is_strava_workout_still_checks_source(self):
        """isStravaWorkout must still check the source field."""
        fn_body = self._get_fn_body()
        assert "source" in fn_body, "isStravaWorkout must still check workout.source"

    def test_is_strava_workout_still_checks_url(self):
        """isStravaWorkout must still check strava_activity_url."""
        fn_body = self._get_fn_body()
        assert "strava_activity_url" in fn_body, (
            "isStravaWorkout must still check strava_activity_url"
        )


# ── AC2: _workoutDictToEntry falls back to w.has_strava ──────────────────────

class TestWorkoutDictToEntryHasStravaFallback:
    """AC2: _workoutDictToEntry must fall back to the backend w.has_strava field
    so that list-view pk-only workouts keep their badge.

    The list API (_workout_list_dict) does NOT expose strava_activity_pk — it
    exposes has_strava (computed correctly on the backend). Without a fallback
    to w.has_strava, a pk-only workout in the list view gets has_strava=false.
    """

    def _get_fn_body(self):
        fn_start = _LOG_JS.find("function _workoutDictToEntry(")
        assert fn_start != -1, "_workoutDictToEntry not found in training-log.js"
        depth = 0
        fn_end = fn_start
        for i in range(fn_start, len(_LOG_JS)):
            if _LOG_JS[i] == "{":
                depth += 1
            elif _LOG_JS[i] == "}":
                depth -= 1
                if depth == 0:
                    fn_end = i
                    break
        return _LOG_JS[fn_start : fn_end + 1]

    def test_workout_dict_to_entry_has_strava_uses_backend_field(self):
        """has_strava in _workoutDictToEntry must reference w.has_strava so that
        workouts correctly marked by the backend are not silently downgraded."""
        fn_body = self._get_fn_body()
        assert "w.has_strava" in fn_body, (
            "_workoutDictToEntry must reference w.has_strava as a fallback. "
            "The list API does not expose strava_activity_pk, so without this "
            "fallback pk-only Strava workouts lose their badge in the list view."
        )


# ── AC3: Detail endpoint exposes strava_activity_pk ─────────────────────────

class TestDetailEndpointExposesStravaActivityPk:
    """AC3: GET /api/workouts/{id} must return strava_activity_pk so the JS
    isStravaWorkout call in the detail panel can use it."""

    def test_workout_detail_includes_strava_activity_pk(self):
        client = _make_client()
        wid = None
        try:
            res = client.post("/api/workouts", json={
                "workout_date": "2026-01-15",
                "name": "PK field presence test",
                "workout_type": "run",
            })
            assert res.status_code == 201, res.text
            wid = res.json()["id"]

            detail = client.get(f"/api/workouts/{wid}")
            assert detail.status_code == 200, detail.text
            body = detail.json()
            assert "strava_activity_pk" in body, (
                "GET /api/workouts/{id} must expose strava_activity_pk so the "
                "JS detail-panel isStravaWorkout call works correctly"
            )
            # For a non-Strava workout the value is null, not absent
            assert body["strava_activity_pk"] is None
        finally:
            if wid:
                client.delete(f"/api/workouts/{wid}")
            _teardown()


# ── AC4: has_strava and has_stryd use consistent pk-check logic ──────────────

class TestHasStravaHasStrydConsistency:
    """AC4: has_strava (via isStravaWorkout) and has_stryd must both check their
    respective activity_pk fields so the two badges are derived symmetrically."""

    def test_has_stryd_checks_stryd_activity_pk(self):
        """has_stryd in _workoutDictToEntry must check stryd_activity_pk —
        confirming the pre-existing consistent behaviour is preserved."""
        fn_start = _LOG_JS.find("function _workoutDictToEntry(")
        assert fn_start != -1
        depth = 0
        fn_end = fn_start
        for i in range(fn_start, len(_LOG_JS)):
            if _LOG_JS[i] == "{":
                depth += 1
            elif _LOG_JS[i] == "}":
                depth -= 1
                if depth == 0:
                    fn_end = i
                    break
        fn_body = _LOG_JS[fn_start : fn_end + 1]
        assert "stryd_activity_pk" in fn_body, (
            "_workoutDictToEntry must still check stryd_activity_pk for has_stryd"
        )

    def test_is_strava_workout_pk_check_consistent_with_has_stryd(self):
        """has_stryd uses !!w.stryd_activity_pk; has_strava must now also use
        !!workout.strava_activity_pk inside isStravaWorkout for symmetry."""
        fn_start = _LOG_JS.find("function isStravaWorkout(")
        depth = 0
        fn_end = fn_start
        for i in range(fn_start, len(_LOG_JS)):
            if _LOG_JS[i] == "{":
                depth += 1
            elif _LOG_JS[i] == "}":
                depth -= 1
                if depth == 0:
                    fn_end = i
                    break
        fn_body = _LOG_JS[fn_start : fn_end + 1]
        assert "strava_activity_pk" in fn_body, (
            "isStravaWorkout must check strava_activity_pk, mirroring how "
            "_workoutDictToEntry checks stryd_activity_pk for has_stryd"
        )
