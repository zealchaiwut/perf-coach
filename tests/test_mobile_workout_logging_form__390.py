"""Tests for issue #390 (superseded): workout logging entry points.

The #390 quick-log modal (workout-form.js) was retired in favor of a single
logging surface: the full editor at /training with the structured run
builder. Every "Log workout" entry point navigates there.

Static checks read source files from the UAT repo.
API tests hit the live UAT server with session auth.
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

_UAT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_HOME_HTML = _UAT_ROOT / "frontend" / "pages" / "home.html"
_LOG_HTML = _UAT_ROOT / "frontend" / "pages" / "training-log.html"
_TRAINING_HTML = _UAT_ROOT / "frontend" / "pages" / "training.html"
_WORKOUT_FORM_JS = _UAT_ROOT / "frontend" / "js" / "workout-form.js"
_HOME_JS = _UAT_ROOT / "frontend" / "js" / "home.js"
_TRAINING_JS = _UAT_ROOT / "frontend" / "js" / "training.js"
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


# ── Single logging surface ────────────────────────────────────────────────────


def test_workout_logging__quick_log_modal_removed():
    # The redundant quick-log modal is gone; /training is the only form.
    assert not _WORKOUT_FORM_JS.exists(), \
        "workout-form.js should be deleted (single logging surface)"
    assert 'src="js/workout-form.js"' not in _HOME_HTML.read_text(), \
        "home.html must not load workout-form.js"
    assert 'src="js/workout-form.js"' not in _LOG_HTML.read_text(), \
        "training-log.html must not load workout-form.js"


def test_workout_logging__home_entry_points_open_full_editor():
    js = _HOME_JS.read_text()
    assert "WorkoutForm" not in js, "home.js must not reference the removed modal"
    assert "/training" in js, "home Log-workout buttons must navigate to /training"
    html = _HOME_HTML.read_text()
    assert "sticky" in html.lower(), \
        "home.html keeps the sticky mobile Log workout button (now navigating to /training)"


def test_workout_logging__training_log_entry_points_open_full_editor():
    js = _TRAINING_LOG_JS.read_text()
    assert "WorkoutForm" not in js, "training-log.js must not reference the removed modal"
    assert "/training?return=/log" in js, \
        "training-log Log-workout buttons must navigate to the full editor"


# ── Full editor: structured run builder ──────────────────────────────────────


def test_workout_logging__training_page_has_segment_builder():
    html = _TRAINING_HTML.read_text()
    for el in ("run-section", "segments-list", "add-segment-menu", "seg-tpl-chip"):
        assert el in html, f"training.html must contain the segment builder element '{el}'"


def test_workout_logging__run_builder_segment_types_and_templates():
    js = _TRAINING_JS.read_text()
    for fn in ("addSegmentRow", "seedTemplate", "getSegments", "recomputeSegments"):
        assert fn in js, f"training.js must define {fn}"
    for tpl in ("easy", "intervals", "tempo"):
        assert tpl in js, f"training.js must ship the built-in '{tpl}' template"


# ── API: workout create (unchanged contract) ─────────────────────────────────


def test_workout_logging__post_run_workout_returns_201(auth_client):
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


def test_workout_logging__post_run_with_segments_returns_201(auth_client):
    # Segments ride in workout_exercises rows (no migration).
    today = datetime.date.today().isoformat()
    r = auth_client.post("/api/workouts", json={
        "name": "Interval session",
        "workout_date": today,
        "workout_type": "Running",
        "distance_km": 4.4,
        "duration_seconds": 1800,
        "exercises": [
            {"display_order": 0, "name": "Warm-up", "distance_km": 1.0},
            {"display_order": 1, "name": "Intervals", "sets": 4,
             "distance_km": 0.4, "duration": "rest 200m"},
            {"display_order": 2, "name": "Cool-down", "distance_km": 1.0},
        ],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    names = [e["name"] for e in body.get("exercises", [])]
    assert names == ["Warm-up", "Intervals", "Cool-down"], names


def test_workout_logging__post_strength_workout_returns_201(auth_client):
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


def test_workout_logging__blank_name_rejected_by_api(auth_client):
    today = datetime.date.today().isoformat()
    r = auth_client.post("/api/workouts", json={
        "name": "",
        "workout_date": today,
        "workout_type": "run",
        "distance_km": 5.0,
        "duration_seconds": 1800,
    })
    assert r.status_code == 422, \
        "API must reject blank name; the form always supplies one"
