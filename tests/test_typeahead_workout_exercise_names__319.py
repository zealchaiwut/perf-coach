"""Tests for issue #319: Type-ahead datalist suggestions for workout and exercise names.

Acceptance criteria verified:
(a) training.html has <datalist id="workout-name-suggestions"> linked to workout name input
(b) training.html workout name input has list="workout-name-suggestions"
(c) training.html has <datalist id="exercise-name-suggestions">
(d) training.js exercise row template includes list="exercise-name-suggestions"
(e) training.js defines loadSuggestions function
(f) loadSuggestions uses /api/workouts endpoint — no new endpoint introduced
(g) loadSuggestions deduplicates workout names
(h) loadSuggestions handles empty workouts list gracefully (early return)
(i) Errors are swallowed — suggestions never block the form
(j) loadSuggestions called on userReady
(k) loadSuggestions called on userChanged
(l) API: GET /api/workouts returns name field for each workout
(m) API: GET /api/workouts/{id} returns exercises[].name
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


def _find_frontend_root() -> pathlib.Path:
    tester_js = _TESTER_ROOT / "frontend" / "js" / "training.js"
    if tester_js.exists() and "loadSuggestions" in tester_js.read_text():
        return _TESTER_ROOT
    if (_CODER_ROOT / "frontend" / "js" / "training.js").exists():
        return _CODER_ROOT
    return _TESTER_ROOT


_ROOT = _find_frontend_root()
_TRAINING_JS = (_ROOT / "frontend" / "js" / "training.js").read_text()
_TRAINING_HTML = (_ROOT / "frontend" / "pages" / "training.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today().isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "typeahead-319-pw"

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
    name = f"Typeahead319_{_RUN}"
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


# ── (a) HTML: datalist for workout names linked to input ─────────────────────

def test_html_workout_datalist_exists():
    assert 'id="workout-name-suggestions"' in _TRAINING_HTML, (
        "Expected <datalist id='workout-name-suggestions'> in training.html"
    )


def test_html_workout_input_has_list_attr():
    assert 'list="workout-name-suggestions"' in _TRAINING_HTML, (
        "Workout name input must have list='workout-name-suggestions'"
    )


def test_html_workout_datalist_is_datalist_element():
    idx = _TRAINING_HTML.index('id="workout-name-suggestions"')
    snippet = _TRAINING_HTML[max(0, idx - 20): idx + 50]
    assert "<datalist" in snippet, (
        "workout-name-suggestions must be a <datalist> element"
    )


# ── (b) Already covered by test_html_workout_input_has_list_attr ─────────────

# ── (c) HTML: datalist for exercise names ────────────────────────────────────

def test_html_exercise_datalist_exists():
    assert 'id="exercise-name-suggestions"' in _TRAINING_HTML, (
        "Expected <datalist id='exercise-name-suggestions'> in training.html"
    )


def test_html_exercise_datalist_is_datalist_element():
    idx = _TRAINING_HTML.index('id="exercise-name-suggestions"')
    snippet = _TRAINING_HTML[max(0, idx - 20): idx + 50]
    assert "<datalist" in snippet, (
        "exercise-name-suggestions must be a <datalist> element"
    )


# ── (d) JS: dynamic exercise row has list attr ───────────────────────────────

def test_js_exercise_row_has_list_attr():
    assert 'list="exercise-name-suggestions"' in _TRAINING_JS, (
        "Dynamically created exercise name input must have list='exercise-name-suggestions'"
    )


def test_js_exercise_list_attr_on_text_input():
    idx = _TRAINING_JS.index('list="exercise-name-suggestions"')
    snippet = _TRAINING_JS[max(0, idx - 80): idx + 60]
    assert 'type="text"' in snippet or "ex-name" in snippet, (
        "list='exercise-name-suggestions' must be on the exercise name text input"
    )


# ── (e) JS: loadSuggestions function ─────────────────────────────────────────

def test_js_has_loadSuggestions_function():
    assert "function loadSuggestions" in _TRAINING_JS or "async function loadSuggestions" in _TRAINING_JS, (
        "training.js must define loadSuggestions()"
    )


# ── (f) No new endpoint — uses existing /api/workouts ────────────────────────

def test_js_calls_existing_workouts_endpoint():
    fn_idx = _TRAINING_JS.index("function loadSuggestions")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 2000]
    assert "/api/workouts" in fn_body


def test_js_no_new_suggestions_endpoint():
    assert "/api/suggestions" not in _TRAINING_JS
    assert "/api/workouts/suggestions" not in _TRAINING_JS
    assert "/api/exercise-names" not in _TRAINING_JS


# ── (g) JS: deduplication of workout names ───────────────────────────────────

def test_js_deduplicates_workout_names():
    fn_idx = _TRAINING_JS.index("function loadSuggestions")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 2000]
    assert "seen" in fn_body, (
        "loadSuggestions must deduplicate workout names using a seen-set pattern"
    )


# ── (h) JS: empty workouts guard ─────────────────────────────────────────────

def test_js_empty_workouts_guard():
    fn_idx = _TRAINING_JS.index("function loadSuggestions")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 2000]
    assert "!workouts.length" in fn_body or "workouts.length === 0" in fn_body or "workouts.length == 0" in fn_body, (
        "loadSuggestions must return early when workouts list is empty"
    )


# ── (i) JS: errors swallowed, form never blocked ─────────────────────────────

def test_js_suggestions_error_is_caught():
    fn_idx = _TRAINING_JS.index("function loadSuggestions")
    fn_body = _TRAINING_JS[fn_idx: fn_idx + 2000]
    assert "catch" in fn_body, (
        "loadSuggestions must catch errors so the form is never blocked"
    )


# ── (j) JS: loadSuggestions called on userReady ──────────────────────────────

def test_js_loadSuggestions_called_on_userReady():
    user_ready_idx = _TRAINING_JS.index("userReady")
    snippet = _TRAINING_JS[user_ready_idx: user_ready_idx + 200]
    assert "loadSuggestions" in snippet, (
        "loadSuggestions() must be called inside the userReady handler"
    )


# ── (k) JS: loadSuggestions called on userChanged ────────────────────────────

def test_js_loadSuggestions_called_on_userChanged():
    user_changed_idx = _TRAINING_JS.index("userChanged")
    snippet = _TRAINING_JS[user_changed_idx: user_changed_idx + 200]
    assert "loadSuggestions" in snippet, (
        "loadSuggestions() must be called inside the userChanged handler"
    )


# ── (l) API: workouts list returns name field ────────────────────────────────

def test_api_workouts_list_returns_name_field(auth_user):
    ac = auth_user["client"]
    payload = {
        "name": f"TypeaheadWkt_{_RUN}",
        "workout_date": "2025-03-01",
        "workout_type": "Strength",
        "exercises": [],
    }
    create_res = ac.post("/api/workouts", json=payload)
    assert create_res.status_code == 201, create_res.text
    wid = create_res.json()["id"]

    try:
        list_res = ac.get("/api/workouts", params={"from": "2025-01-01", "to": TODAY})
        assert list_res.status_code == 200
        workouts = list_res.json()
        assert isinstance(workouts, list)
        match = next((w for w in workouts if w["id"] == wid), None)
        assert match is not None, "Created workout not found in list"
        assert "name" in match, "Workout list items must include 'name' field"
        assert match["name"] == f"TypeaheadWkt_{_RUN}"
    finally:
        ac.delete(f"/api/workouts/{wid}")


def test_api_workouts_list_returns_no_duplicates_for_same_user(auth_user):
    """Sanity: same workout name created twice still appears as two distinct entries (API dedup is JS-side)."""
    ac = auth_user["client"]
    ids = []
    for i in range(2):
        res = ac.post("/api/workouts", json={
            "name": f"DupName_{_RUN}",
            "workout_date": f"2025-04-0{i + 1}",
            "workout_type": "Run",
            "exercises": [],
        })
        assert res.status_code == 201, res.text
        ids.append(res.json()["id"])

    try:
        list_res = ac.get("/api/workouts", params={"from": "2025-01-01", "to": TODAY})
        assert list_res.status_code == 200
        workouts = list_res.json()
        dup_entries = [w for w in workouts if w["name"] == f"DupName_{_RUN}"]
        assert len(dup_entries) == 2, "API returns all entries; JS deduplication happens client-side"
    finally:
        for wid in ids:
            ac.delete(f"/api/workouts/{wid}")


# ── (m) API: workout detail returns exercises[].name ────────────────────────

def test_api_workout_detail_returns_exercise_names(auth_user):
    ac = auth_user["client"]
    payload = {
        "name": f"ExNameTest_{_RUN}",
        "workout_date": "2025-03-15",
        "workout_type": "Strength",
        "exercises": [
            {"name": "Squat", "sets": 3, "reps": 5, "weight_kg": 100.0, "display_order": 0},
            {"name": "Deadlift", "sets": 3, "reps": 3, "weight_kg": 140.0, "display_order": 1},
        ],
    }
    create_res = ac.post("/api/workouts", json=payload)
    assert create_res.status_code == 201, create_res.text
    wid = create_res.json()["id"]

    try:
        detail_res = ac.get(f"/api/workouts/{wid}")
        assert detail_res.status_code == 200
        data = detail_res.json()
        assert "exercises" in data, "Workout detail must include exercises array"
        assert len(data["exercises"]) == 2
        ex_names = [e["name"] for e in data["exercises"]]
        assert "Squat" in ex_names
        assert "Deadlift" in ex_names
    finally:
        ac.delete(f"/api/workouts/{wid}")


def test_api_no_workout_history_returns_empty_list(auth_user):
    """New user with no workouts: endpoint returns [] — JS early-return handles this."""
    ac = auth_user["client"]
    list_res = ac.get("/api/workouts", params={"from": "1990-01-01", "to": "1990-12-31"})
    assert list_res.status_code == 200
    assert list_res.json() == [], "Empty date range must return empty list, not error"
