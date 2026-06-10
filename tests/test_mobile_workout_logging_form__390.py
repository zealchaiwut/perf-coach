"""Tests for issue #390: Build mobile-first workout logging form (runs against UAT).

Static checks read source files from the UAT repo (feature/390 branch).
API tests hit the live UAT server with session auth.
Risk: MEDIUM → 1-2 tests per criterion.
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

from backend.auth import hash_password

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT."
    )

# UAT repo root — must be on feature/390-mobile-workout-logging-form
_UAT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / "uat"
_HOME_HTML = _UAT_ROOT / "frontend" / "pages" / "home.html"
_LOG_HTML = _UAT_ROOT / "frontend" / "pages" / "training-log.html"
_WORKOUT_FORM_JS = _UAT_ROOT / "frontend" / "js" / "workout-form.js"
_HOME_JS = _UAT_ROOT / "frontend" / "js" / "home.js"
_TRAINING_LOG_JS = _UAT_ROOT / "frontend" / "js" / "training-log.js"

_uat_cfg = dotenv_values(str(_UAT_ROOT / ".env"))
_uat_db_url = _uat_cfg.get("DATABASE_URL_UAT") or _uat_cfg.get("DATABASE_URL")
_engine = create_engine(_uat_db_url, pool_pre_ping=True)


def _create_user(name: str, password: str) -> str:
    pw_hash = hash_password(password)
    with _engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name, password_hash) VALUES (:n, :p) RETURNING id"),
            {"n": name, "p": pw_hash},
        ).fetchone()
    return str(row.id)


def _delete_user(uid: str) -> None:
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = CAST(:u AS uuid)"), {"u": uid})


def _login_client(username: str, password: str) -> httpx.Client:
    tmp = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = tmp.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    session_val = tmp.cookies.get("session", "")
    tmp.close()
    assert session_val, "session cookie missing after login"

    csrf_tmp = httpx.Client(base_url=BASE_URL, timeout=10.0, cookies={"session": session_val})
    csrf_resp = csrf_tmp.get("/api/csrf-token")
    assert csrf_resp.status_code == 200, f"CSRF fetch failed: {csrf_resp.text}"
    csrf = csrf_resp.json()["csrf_token"]
    csrf_tmp.close()

    return httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        follow_redirects=True,
        cookies={"session": session_val, "csrf-token": csrf},
        headers={"X-CSRF-Token": csrf},
    )


@pytest.fixture(scope="module")
def auth_client():
    username = f"tester390_{uuid.uuid4().hex[:8]}"
    password = "TestPass390!"
    uid = _create_user(username, password)
    c = _login_client(username, password)
    yield c
    c.close()
    _delete_user(uid)


# ── Form Access ───────────────────────────────────────────────────────────────

def test_mobile_workout_logging_form__workout_form_js_exists():
    # AC: workout-form.js exists at frontend/js/workout-form.js
    assert _WORKOUT_FORM_JS.exists(), "frontend/js/workout-form.js must exist"
    assert _WORKOUT_FORM_JS.stat().st_size > 0


def test_mobile_workout_logging_form__home_page_has_cta_and_loads_form():
    # AC: "Log workout" CTA on home page; all entry points open workout-form.js
    html = _HOME_HTML.read_text()
    js = _HOME_JS.read_text()
    assert "Log workout" in html, "home.html must contain 'Log workout' text"
    assert 'src="js/workout-form.js"' in html, "home.html must load workout-form.js"
    assert "WorkoutForm" in js and "open" in js, "home.js must call WorkoutForm.open()"


def test_mobile_workout_logging_form__training_log_has_entry_point():
    # AC: "Log workout" entry on training-log.html; opens same form
    html = _LOG_HTML.read_text()
    js = _TRAINING_LOG_JS.read_text()
    assert "Log workout" in html, "training-log.html must contain 'Log workout'"
    assert 'src="js/workout-form.js"' in html, "training-log.html must load workout-form.js"
    assert "WorkoutForm" in js and "open" in js, "training-log.js must call WorkoutForm.open()"


def test_mobile_workout_logging_form__sticky_mobile_button():
    # AC: sticky "Log workout" button present on mobile (≤500px)
    html = _HOME_HTML.read_text()
    assert "sticky-log-btn" in html or "sticky" in html.lower(), \
        "home.html must have a sticky Log workout button element"
    assert "500px" in html, "home.html must scope sticky button to ≤500px media query"


# ── Workout Type Selector ─────────────────────────────────────────────────────

def test_mobile_workout_logging_form__type_selector_run_and_strength_only():
    # AC: form shows exactly Run and Strength options
    js = _WORKOUT_FORM_JS.read_text()
    assert "'run'" in js or '"run"' in js, "workout-form.js must have run type"
    assert "'strength'" in js or '"strength"' in js, "workout-form.js must have strength type"
    assert "Run" in js and "Strength" in js


def test_mobile_workout_logging_form__type_swap_fields_without_reload():
    # AC: selecting a type swaps fields without page reload
    pytest.skip("manual — cannot be HTTP-tested (requires browser interaction)")


# ── Run Variant Fields ────────────────────────────────────────────────────────

def test_mobile_workout_logging_form__run_fields_and_defaults():
    # AC: run form has Bangkok-TZ date default, required distance/duration, optional avg_hr/zone2/notes
    js = _WORKOUT_FORM_JS.read_text()
    assert "Asia/Bangkok" in js, "workout-form.js must use Asia/Bangkok for default date"
    assert '"Run"' in js or "'Run'" in js, "workout-form.js must default run name to 'Run'"
    assert "distance_km" in js
    assert "duration_minutes" in js
    assert "zone2_minutes" in js
    assert "avg_hr" in js


def test_mobile_workout_logging_form__run_field_constraints():
    # AC: distance_km 0.1–100; duration 1–480; avg_hr 80–220; zone2 0–duration; notes ≤500
    js = _WORKOUT_FORM_JS.read_text()
    assert "0.1" in js and '"100"' in js or "max=\"100\"" in js or "max=100" in js or ", 100" in js
    assert "480" in js, "workout-form.js must set duration_minutes max=480"
    assert "80" in js and "220" in js, "workout-form.js must set avg_hr range 80–220"
    assert "500" in js, "workout-form.js must set notes maxlength=500"


# ── Strength Variant Fields ───────────────────────────────────────────────────

def test_mobile_workout_logging_form__strength_fields_and_defaults():
    # AC: strength form has Bangkok-TZ date, duration (required), exercises textarea, avg_hr, notes
    js = _WORKOUT_FORM_JS.read_text()
    assert "Strength training" in js, "workout-form.js must default strength name to 'Strength training'"
    assert "exercises" in js
    assert "2000" in js, "workout-form.js must set exercises maxlength=2000"


# ── Validation ────────────────────────────────────────────────────────────────

def test_mobile_workout_logging_form__required_field_validation_and_inline_errors():
    # AC: required fields validated client-side; out-of-range shows inline error
    js = _WORKOUT_FORM_JS.read_text()
    assert "is required" in js, "workout-form.js must show 'is required' error messages"
    assert "wf-error" in js, "workout-form.js must render inline wf-error elements"


def test_mobile_workout_logging_form__zone2_le_duration_validation():
    # AC: zone2_minutes > duration_minutes shows a validation error
    js = _WORKOUT_FORM_JS.read_text()
    assert "Zone 2 minutes cannot exceed duration" in js, \
        "workout-form.js must validate zone2_minutes <= duration_minutes"


def test_mobile_workout_logging_form__char_count_display():
    # AC: character-limit fields show remaining count or error when exceeded
    js = _WORKOUT_FORM_JS.read_text()
    assert "remaining" in js, "workout-form.js must show remaining character count"


# ── Save Behaviour ────────────────────────────────────────────────────────────

def test_mobile_workout_logging_form__posts_to_api_workouts_endpoint():
    # AC: Submit button POSTs to POST /api/workouts
    js = _WORKOUT_FORM_JS.read_text()
    assert "/api/workouts" in js, "workout-form.js must POST to /api/workouts"
    assert "method: 'POST'" in js or 'method: "POST"' in js


def test_mobile_workout_logging_form__post_run_workout_returns_201(auth_client):
    # AC: on 2xx response, workout is saved; run with blank name sends name="Run"
    today = datetime.date.today().isoformat()
    r = auth_client.post("/api/workouts", json={
        "name": "Run",
        "workout_date": today,
        "workout_type": "run",
        "distance_km": 5.0,
        "duration_seconds": 1800,
        "exercises": [],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Run"
    assert body["workout_type"] == "run"


def test_mobile_workout_logging_form__post_strength_workout_returns_201(auth_client):
    # AC: strength form with blank name sends "Strength training"; POST returns 201
    today = datetime.date.today().isoformat()
    r = auth_client.post("/api/workouts", json={
        "name": "Strength training",
        "workout_date": today,
        "workout_type": "strength",
        "duration_seconds": 2700,
        "exercises": [],
    })
    assert r.status_code == 201, r.text
    assert r.json()["workout_type"] == "strength"


def test_mobile_workout_logging_form__blank_name_rejected_by_api(auth_client):
    # AC: frontend always fills "Run"/"Strength training"; blank name is rejected server-side
    today = datetime.date.today().isoformat()
    r = auth_client.post("/api/workouts", json={
        "name": "",
        "workout_date": today,
        "workout_type": "run",
        "distance_km": 5.0,
        "duration_seconds": 1800,
    })
    assert r.status_code == 422, \
        "API must reject blank name; frontend must always substitute a default"


def test_mobile_workout_logging_form__error_handling_keeps_form_open():
    # AC: on error response, toast/inline error shown; form stays open
    js = _WORKOUT_FORM_JS.read_text()
    assert "submitBtn.disabled = false" in js, \
        "workout-form.js must re-enable submit button on error"
    assert "wf-submit-err" in js, "workout-form.js must surface error via wf-submit-err"


def test_mobile_workout_logging_form__success_toast_message():
    # AC: on 2xx, "Workout logged" toast appears
    js = _WORKOUT_FORM_JS.read_text()
    assert "Workout logged" in js, "workout-form.js must show 'Workout logged' toast on success"


# ── Layout ────────────────────────────────────────────────────────────────────

def test_mobile_workout_logging_form__single_column_touch_targets():
    # AC: single-column layout, large touch targets (≥44px) at ≤500px
    js = _WORKOUT_FORM_JS.read_text()
    assert "flex-direction:column" in js or "flex-direction: column" in js, \
        "workout-form.js must use flex-direction:column for single-column layout"
    assert "min-height:44px" in js or "min-height: 44px" in js, \
        "workout-form.js must set min-height:44px for touch targets"


def test_mobile_workout_logging_form__no_horizontal_scroll_375px():
    # AC: form usable without horizontal scroll on 375px width
    pytest.skip("manual — cannot be HTTP-tested (requires browser viewport check)")


def test_mobile_workout_logging_form__no_console_errors():
    # AC: zero console errors on open, fill, submit, close
    pytest.skip("manual — cannot be HTTP-tested (requires browser console)")
