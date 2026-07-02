"""Tests for issue #318: Repeat last workout shortcut on training form.

Acceptance criteria verified:
(a) training.html has #repeat-last-btn visible in the New Workout form area
(b) training.js defines repeatLastWorkout function
(c) JS fetches most recent workout via existing /api/workouts endpoint (no new endpoint)
(d) JS prefills name, workout_type, remarks, TSS fields
(e) JS populates exercise rows via addExerciseRow
(f) JS sets date to todayIso() (client local date), not source workout date
(g) JS shows informative toast when no previous workout exists
(h) editingWorkoutId reset to null so save creates a new record
(i) API: GET /api/workouts returns workouts ordered most-recent first
(j) API: GET /api/workouts/{id} returns exercises list
(k) API: POST /api/workouts creates new workout; original unmodified
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from backend.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

# ── Path detection: prefer tester root post-merge, coder root pre-merge ──────
_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_js_root() -> pathlib.Path:
    tester_js = _TESTER_ROOT / "frontend" / "js" / "training.js"
    if tester_js.exists() and "repeatLastWorkout" in tester_js.read_text():
        return _TESTER_ROOT
    if (_CODER_ROOT / "frontend" / "js" / "training.js").exists():
        return _CODER_ROOT
    return _TESTER_ROOT


_ROOT = _find_js_root()
_TRAINING_JS = (_ROOT / "frontend" / "js" / "training.js").read_text()
_TRAINING_HTML = (_ROOT / "frontend" / "pages" / "training.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today().isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "repeat-wkt-318-pw"

_env_vals = dotenv_values(_TESTER_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"RptWkt318_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]

    pw_hash = hash_password(_TEST_PASSWORD)
    with DBSession(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = pw_hash
        session.commit()

    login_res = client.post(
        "/api/auth/login",
        json={"username": name, "password": _TEST_PASSWORD},
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"

    session_cookie = login_res.cookies.get("session")
    assert session_cookie, "Login must set session cookie"

    csrf_token = generate_csrf_token()

    authed = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )

    yield {"id": user_id, "name": name, "client": authed}

    authed.close()
    client.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


# ── (a) HTML structure ────────────────────────────────────────────────────────

def test_repeat_btn_present_in_html():
    assert 'id="repeat-last-btn"' in _TRAINING_HTML, (
        "Expected #repeat-last-btn button in training.html"
    )


def test_repeat_btn_label():
    idx = _TRAINING_HTML.index('id="repeat-last-btn"')
    snippet = _TRAINING_HTML[idx: idx + 100]
    assert "Repeat last workout" in snippet, (
        "Button must be labelled 'Repeat last workout'"
    )


def test_repeat_btn_in_new_workout_form():
    """Button must appear inside the form-actions bar (not in history view)."""
    btn_idx = _TRAINING_HTML.index('id="repeat-last-btn"')
    form_start = _TRAINING_HTML.rfind("form-actions", 0, btn_idx)
    assert form_start != -1, (
        "repeat-last-btn should appear within the form-actions section"
    )


def test_repeat_btn_is_type_button():
    idx = _TRAINING_HTML.index('id="repeat-last-btn"')
    snippet = _TRAINING_HTML[max(0, idx - 100): idx + 50]
    assert 'type="button"' in snippet, "repeat-last-btn must be type='button' to avoid form submit"


# ── (b) JS has repeatLastWorkout function ─────────────────────────────────────

def test_js_has_repeatLastWorkout_function():
    assert "function repeatLastWorkout" in _TRAINING_JS, (
        "training.js must define repeatLastWorkout()"
    )


def test_repeat_btn_click_handler_wired():
    assert "repeat-last-btn" in _TRAINING_JS, (
        "training.js must reference repeat-last-btn (click handler)"
    )
    assert "repeatLastWorkout" in _TRAINING_JS


# ── (c) Uses existing endpoint, no new endpoint introduced ───────────────────

def test_js_calls_api_workouts_list():
    assert "/api/workouts" in _TRAINING_JS


def test_js_no_new_repeat_endpoint():
    """No new endpoint introduced — feature uses existing /api/workouts paths only."""
    assert "/api/workouts/repeat" not in _TRAINING_JS
    assert "/api/workouts/last" not in _TRAINING_JS
    assert "/api/repeat" not in _TRAINING_JS


def test_js_fetches_individual_workout_for_prefill():
    """Function fetches /api/workouts/{id} to get full detail including exercises."""
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "/api/workouts/" in fn_body


# ── (d–f) Field prefill ───────────────────────────────────────────────────────

def test_js_prefills_name():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "workout-name" in fn_body


def test_js_prefills_workout_type():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "setSelectedType" in fn_body or "workout_type" in fn_body


def test_js_prefills_remarks():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "workout-remarks" in fn_body


def test_js_prefills_tss():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "workout-tss" in fn_body


def test_js_populates_exercise_rows():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "addExerciseRow" in fn_body


# ── (f) Date set to today, not source date ───────────────────────────────────

def test_js_sets_date_to_today():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "workout-date" in fn_body
    assert "todayIso()" in fn_body or "todayIso" in fn_body


def test_js_does_not_copy_source_workout_date():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "workout_date" not in fn_body, (
        "Should not copy source workout's date — date must be today"
    )


# ── (g) No previous workout handling ─────────────────────────────────────────

def test_js_handles_empty_history():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "No previous workout" in fn_body or "showToast" in fn_body


# ── (h) New workout (not edit) ────────────────────────────────────────────────

def test_js_resets_editingWorkoutId():
    fn_idx = _TRAINING_JS.index("function repeatLastWorkout")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 1600]
    assert "editingWorkoutId" in fn_body, (
        "editingWorkoutId must be reset to null so save creates a new record"
    )


# ── (i) API: workouts returned most-recent first ─────────────────────────────

def test_api_workouts_sorted_desc(auth_user):
    ac = auth_user["client"]
    payload_old = {
        "name": "Older Workout",
        "workout_date": "2020-01-01",
        "workout_type": "Strength",
        "exercises": [],
    }
    payload_new = {
        "name": "Newer Workout",
        "workout_date": "2020-06-15",
        "workout_type": "Running",
        "exercises": [],
    }

    old_res = ac.post("/api/workouts", json=payload_old)
    new_res = ac.post("/api/workouts", json=payload_new)
    assert old_res.status_code == 201, old_res.text
    assert new_res.status_code == 201, new_res.text
    old_id = old_res.json()["id"]
    new_id = new_res.json()["id"]

    try:
        list_res = ac.get("/api/workouts", params={"from": "2019-01-01", "to": TODAY})
        assert list_res.status_code == 200
        workouts = list_res.json()
        ids = [w["id"] for w in workouts]
        assert new_id in ids and old_id in ids
        assert ids.index(new_id) < ids.index(old_id), (
            "Most recent workout must appear first (desc order)"
        )
    finally:
        ac.delete(f"/api/workouts/{old_id}")
        ac.delete(f"/api/workouts/{new_id}")


# ── (j) API: workout detail includes exercises ───────────────────────────────

def test_api_workout_detail_includes_exercises(auth_user):
    ac = auth_user["client"]
    payload = {
        "name": "Exercise Detail Test",
        "workout_date": "2020-03-10",
        "workout_type": "Strength",
        "exercises": [
            {"name": "Squat", "sets": 3, "reps": 5, "weight_kg": 100.0, "display_order": 0},
            {"name": "Bench", "sets": 4, "reps": 8, "weight_kg": 70.0, "display_order": 1},
        ],
    }
    create_res = ac.post("/api/workouts", json=payload)
    assert create_res.status_code == 201, create_res.text
    wid = create_res.json()["id"]

    try:
        detail_res = ac.get(f"/api/workouts/{wid}")
        assert detail_res.status_code == 200
        data = detail_res.json()
        assert "exercises" in data
        assert len(data["exercises"]) == 2
        names = [e["name"] for e in data["exercises"]]
        assert "Squat" in names and "Bench" in names
    finally:
        ac.delete(f"/api/workouts/{wid}")


# ── (k) Repeat creates new workout, original unchanged ───────────────────────

def test_api_repeat_creates_new_record_original_unchanged(auth_user):
    ac = auth_user["client"]
    original_payload = {
        "name": "Original Workout",
        "workout_date": "2020-04-01",
        "workout_type": "Running",
        "tss": 85,
        "remarks": "Easy run",
        "exercises": [],
    }
    create_res = ac.post("/api/workouts", json=original_payload)
    assert create_res.status_code == 201, create_res.text
    original_id = create_res.json()["id"]

    repeat_payload = {
        "name": "Original Workout",
        "workout_date": TODAY,
        "workout_type": "Running",
        "tss": 90,
        "remarks": "Easy run",
        "exercises": [],
    }
    repeat_res = ac.post("/api/workouts", json=repeat_payload)
    assert repeat_res.status_code == 201, repeat_res.text
    repeat_id = repeat_res.json()["id"]

    try:
        assert repeat_id != original_id, "Repeat must create a new record"

        orig_detail = ac.get(f"/api/workouts/{original_id}")
        assert orig_detail.status_code == 200
        orig_data = orig_detail.json()
        assert orig_data["name"] == "Original Workout"
        assert orig_data["tss"] == 85, "Original TSS must remain unchanged"
        assert orig_data["workout_date"] == "2020-04-01", "Original date must be unchanged"

        repeat_detail = ac.get(f"/api/workouts/{repeat_id}")
        assert repeat_detail.status_code == 200
        repeat_data = repeat_detail.json()
        assert repeat_data["workout_date"] == TODAY, "Repeated workout date must be today"
        assert repeat_data["tss"] == 90
    finally:
        ac.delete(f"/api/workouts/{original_id}")
        ac.delete(f"/api/workouts/{repeat_id}")
