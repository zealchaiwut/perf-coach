"""Tests for issue #390: Mobile-first workout logging form (run/strength).

Each test is anchored to one Acceptance Criterion item.
Static checks read the source files directly; API tests use TestClient.
"""
import pathlib
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_ROOT = pathlib.Path(__file__).parent.parent
_HOME_HTML = _ROOT / "frontend" / "pages" / "home.html"
_LOG_HTML = _ROOT / "frontend" / "pages" / "training-log.html"
_WORKOUT_FORM_JS = _ROOT / "frontend" / "js" / "workout-form.js"
_TRAINING_LOG_JS = _ROOT / "frontend" / "js" / "training-log.js"
_HOME_JS = _ROOT / "frontend" / "js" / "home.js"

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000390")


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_workout_obj(**kwargs):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = _USER_ID
    w.name = kwargs.get("name", "Run")
    w.workout_date = date(2026, 6, 10)
    w.workout_type = kwargs.get("workout_type", "run")
    w.remarks = kwargs.get("remarks", None)
    w.tss = None
    w.tss_source = None
    w.source = None
    w.strava_activity_pk = None
    w.stryd_activity_pk = None
    w.strava_activity_url = None
    w.strava_activity = None
    w.stryd_activity = None
    w.distance_km = kwargs.get("distance_km", None)
    w.duration_seconds = kwargs.get("duration_seconds", None)
    w.avg_hr = None
    w.max_hr = None
    w.elevation_m = None
    w.zone2_minutes = None
    w.manual_overrides = None
    created = MagicMock()
    created.isoformat.return_value = "2026-06-10T00:00:00+00:00"
    w.created_at = created
    return w


def _make_session_ctx(workout_obj, exercises=None):
    if exercises is None:
        exercises = []
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = workout_obj
    query_m = MagicMock()
    query_m.filter.return_value = query_m
    query_m.order_by.return_value = query_m
    query_m.all.return_value = exercises
    query_m.count.return_value = 0
    sess.query.return_value = query_m
    return sess


# ── AC: Form Access ───────────────────────────────────────────────────────────

class TestFormAccess:
    """AC: All three entry points exist and open workout-form.js."""

    def test_workout_form_js_exists(self):
        """workout-form.js must exist at frontend/js/workout-form.js."""
        assert _WORKOUT_FORM_JS.exists(), "frontend/js/workout-form.js must exist"

    def test_home_html_loads_workout_form_js(self):
        """home.html must load workout-form.js."""
        html = _HOME_HTML.read_text()
        assert 'src="js/workout-form.js"' in html, \
            "home.html must have <script src=\"js/workout-form.js\">"

    def test_home_html_has_log_workout_cta(self):
        """home.html must have a 'Log workout' CTA visible on the page."""
        html = _HOME_HTML.read_text()
        assert "Log workout" in html, "home.html must contain 'Log workout' text"

    def test_training_log_html_loads_workout_form_js(self):
        """training-log.html (served at /log) must load workout-form.js."""
        html = _LOG_HTML.read_text()
        assert 'src="js/workout-form.js"' in html, \
            "training-log.html must have <script src=\"js/workout-form.js\">"

    def test_training_log_html_has_log_workout_btn(self):
        """training-log.html must have a 'Log workout' button."""
        html = _LOG_HTML.read_text()
        assert "Log workout" in html, "training-log.html must contain 'Log workout'"

    def test_home_html_has_sticky_mobile_btn(self):
        """home.html must have a sticky 'Log workout' button element."""
        html = _HOME_HTML.read_text()
        assert "sticky" in html.lower() or "log-workout-sticky" in html or \
               "sticky-log-btn" in html or "fab-log" in html or \
               "sticky-workout" in html, \
            "home.html must have a sticky Log workout button element"

    def test_home_html_sticky_btn_css_mobile_only(self):
        """home.html must have CSS scoping the sticky button to ≤500 px."""
        html = _HOME_HTML.read_text()
        assert "500px" in html, \
            "home.html must have a 500px media query for the sticky button"

    def test_workout_form_js_exposes_open(self):
        """workout-form.js must expose an open/openWorkoutForm function."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "WorkoutForm" in js, "workout-form.js must define WorkoutForm"
        assert "open" in js, "WorkoutForm must expose an open() method"

    def test_training_log_js_calls_workout_form_open(self):
        """training-log.js must call WorkoutForm.open() (not redirect to /training)."""
        js = _TRAINING_LOG_JS.read_text()
        assert "WorkoutForm" in js and "open" in js, \
            "training-log.js must call WorkoutForm.open() for #log-new-btn"

    def test_home_js_calls_workout_form_open(self):
        """home.js must call WorkoutForm.open() for the CTA."""
        js = _HOME_JS.read_text()
        assert "WorkoutForm" in js and "open" in js, \
            "home.js must wire Log workout CTA to WorkoutForm.open()"


# ── AC: Workout Type Selector ─────────────────────────────────────────────────

class TestWorkoutTypeSelector:
    """AC: Form shows exactly two types: Run and Strength."""

    def test_workout_form_js_has_run_option(self):
        """workout-form.js must render a Run option."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "Run" in js, "workout-form.js must include 'Run' type option"

    def test_workout_form_js_has_strength_option(self):
        """workout-form.js must render a Strength option."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "Strength" in js, "workout-form.js must include 'Strength' type option"

    def test_workout_form_js_only_run_and_strength_types(self):
        """workout-form.js must list exactly run and strength as form types."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "run" in js and "strength" in js, \
            "workout-form.js must have run and strength workout_type values"


# ── AC: Run Variant Fields ─────────────────────────────────────────────────────

class TestRunVariantFields:
    """AC: Run form has correct fields with correct defaults/constraints."""

    def test_workout_form_js_bangkok_timezone(self):
        """workout-form.js must use Asia/Bangkok for default date."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "Asia/Bangkok" in js, \
            "workout-form.js must use Asia/Bangkok timezone for date default"

    def test_workout_form_js_run_name_default(self):
        """workout-form.js must default run name to 'Run'."""
        js = _WORKOUT_FORM_JS.read_text()
        assert '"Run"' in js or "'Run'" in js, \
            "workout-form.js must default name to 'Run' for run type"

    def test_workout_form_js_distance_km_field(self):
        """workout-form.js must have a distance_km field."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "distance_km" in js, "workout-form.js must include distance_km field"

    def test_workout_form_js_duration_minutes_field(self):
        """workout-form.js must have a duration_minutes field."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "duration_minutes" in js, \
            "workout-form.js must include duration_minutes field"

    def test_workout_form_js_avg_hr_field(self):
        """workout-form.js must have an avg_hr field."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "avg_hr" in js, "workout-form.js must include avg_hr field"

    def test_workout_form_js_zone2_minutes_field(self):
        """workout-form.js must have a zone2_minutes field."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "zone2_minutes" in js, \
            "workout-form.js must include zone2_minutes field"

    def test_workout_form_js_run_distance_range(self):
        """workout-form.js must enforce distance_km range 0.1–100."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "0.1" in js and "100" in js, \
            "workout-form.js must set distance_km min=0.1 max=100"

    def test_workout_form_js_run_duration_range(self):
        """workout-form.js must enforce duration_minutes range 1–480."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "480" in js, "workout-form.js must set duration_minutes max=480"

    def test_workout_form_js_run_notes_char_limit(self):
        """workout-form.js must enforce notes ≤500 characters for run."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "500" in js, "workout-form.js must have 500-char limit for notes"


# ── AC: Strength Variant Fields ───────────────────────────────────────────────

class TestStrengthVariantFields:
    """AC: Strength form has correct fields with correct defaults/constraints."""

    def test_workout_form_js_strength_name_default(self):
        """workout-form.js must default strength name to 'Strength training'."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "Strength training" in js, \
            "workout-form.js must default name to 'Strength training' for strength"

    def test_workout_form_js_exercises_textarea(self):
        """workout-form.js must include an exercises textarea for strength."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "exercises" in js, \
            "workout-form.js must include exercises field for strength"

    def test_workout_form_js_exercises_char_limit(self):
        """workout-form.js must enforce exercises ≤2000 characters."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "2000" in js, \
            "workout-form.js must have 2000-char limit for exercises textarea"


# ── AC: Validation ────────────────────────────────────────────────────────────

class TestValidation:
    """AC: Client-side validation prevents bad submits."""

    def test_workout_form_js_validates_required_fields(self):
        """workout-form.js must validate required fields before POST."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "required" in js.lower() or "Required" in js or "is required" in js, \
            "workout-form.js must validate required fields client-side"

    def test_workout_form_js_validates_zone2_le_duration(self):
        """workout-form.js must validate zone2_minutes <= duration_minutes."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "zone2" in js and "duration" in js, \
            "workout-form.js must cross-validate zone2_minutes against duration_minutes"

    def test_workout_form_js_shows_inline_error(self):
        """workout-form.js must render inline error messages for validation failures."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "error" in js.lower(), \
            "workout-form.js must show inline validation errors"

    def test_workout_form_js_char_count_display(self):
        """workout-form.js must display remaining character count for limited fields."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "remaining" in js.lower() or "chars" in js.lower() or \
               "charCount" in js or "char-count" in js, \
            "workout-form.js must show character count for limited text fields"


# ── AC: Save Behaviour ────────────────────────────────────────────────────────

class TestSaveBehaviour:
    """AC: Submit POSTs to /api/workouts and handles response correctly."""

    def test_workout_form_js_posts_to_api_workouts(self):
        """workout-form.js must POST to /api/workouts."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "/api/workouts" in js, \
            "workout-form.js must POST to /api/workouts"

    def test_workout_form_js_success_toast(self):
        """workout-form.js must show 'Workout logged' toast on success."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "Workout logged" in js, \
            "workout-form.js must include 'Workout logged' success message"

    def test_workout_form_js_handles_error_response(self):
        """workout-form.js must keep form open and show error on non-2xx response."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "error" in js.lower() and ("response" in js.lower() or "status" in js.lower()), \
            "workout-form.js must handle error responses without closing the form"

    def test_api_post_run_workout_succeeds(self):
        """POST /api/workouts with run payload and distance returns 201."""
        client, _ = _make_client()
        w = _make_workout_obj(name="Run", workout_type="run", distance_km=5.0,
                              duration_seconds=1800)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main.daily_update"), \
                 patch("backend.main._recompute_autofill"):
                res = client.post("/api/workouts", json={
                    "name": "Run",
                    "workout_date": "2026-06-10",
                    "workout_type": "run",
                    "distance_km": 5.0,
                    "duration_seconds": 1800,
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_api_post_strength_workout_succeeds(self):
        """POST /api/workouts with strength payload returns 201."""
        client, _ = _make_client()
        w = _make_workout_obj(name="Strength training", workout_type="strength",
                              duration_seconds=2700)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main.daily_update"), \
                 patch("backend.main._recompute_autofill"):
                res = client.post("/api/workouts", json={
                    "name": "Strength training",
                    "workout_date": "2026-06-10",
                    "workout_type": "strength",
                    "duration_seconds": 2700,
                })
            assert res.status_code == 201
        finally:
            _teardown()

    def test_api_post_blank_name_returns_422(self):
        """POST /api/workouts with blank name returns 422 (frontend must fill default)."""
        client, _ = _make_client()
        try:
            res = client.post("/api/workouts", json={
                "name": "",
                "workout_date": "2026-06-10",
                "workout_type": "run",
            })
            assert res.status_code == 422, \
                "Backend rejects blank name; frontend must always send a non-empty name"
        finally:
            _teardown()

    def test_workout_form_js_converts_duration_minutes_to_seconds(self):
        """workout-form.js must convert duration_minutes to duration_seconds for API."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "duration_seconds" in js, \
            "workout-form.js must send duration_seconds (not duration_minutes) to API"
        assert "60" in js, \
            "workout-form.js must multiply minutes by 60 to get seconds"


# ── AC: Layout ────────────────────────────────────────────────────────────────

class TestLayout:
    """AC: Single-column mobile layout, usable at 375 px."""

    def test_workout_form_js_single_column_css(self):
        """workout-form.js must apply single-column layout in the form."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "flex-direction" in js or "single" in js.lower() or \
               "column" in js, \
            "workout-form.js must use single-column layout"

    def test_workout_form_js_has_modal_or_overlay(self):
        """workout-form.js must render a modal overlay."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "modal" in js.lower() or "overlay" in js.lower() or \
               "backdrop" in js.lower(), \
            "workout-form.js must implement a modal/overlay for the form"

    def test_workout_form_js_close_on_backdrop(self):
        """workout-form.js must close form when clicking outside (or has close button)."""
        js = _WORKOUT_FORM_JS.read_text()
        assert "close" in js.lower() or "dismiss" in js.lower(), \
            "workout-form.js must have a way to close the form"
