"""
Tests for issue #1145: Build strength and plyo session entry UI.

Acceptance criteria verified:
- AC1: User can open a session entry form (page accessible at /sessions)
- AC2: Strength form captures exercise name, sets, reps, load (weight + unit)
        → POST /api/strength-sessions stores exercise_name, sets, reps,
          load, load_unit
- AC3: Plyo form captures exercise name, foot-contacts, phase
        → POST /api/plyo-sessions stores exercise_name, foot_contacts,
          plyo_phase
- AC4: Multiple exercises per session
        → Multiple POSTs to the same endpoint work (grouped by date in UI)
- AC5: Edit exercise entry inline
        → PUT /api/strength-sessions/{id} and PUT /api/plyo-sessions/{id}
- AC6: Delete exercise entry
        → DELETE /api/strength-sessions/{id} and DELETE /api/plyo-sessions/{id}
- AC7: POST shows success → API returns 201 on create
- AC8: PUT persists changes → updated fields returned in response
- AC9: DELETE removes record → subsequent GET no longer includes it
- AC10: Sessions reload on refresh
        → GET /api/strength-sessions and GET /api/plyo-sessions
          return persisted data
- AC11: Form validation → missing required fields return 422 with field detail
- AC12: Responsive UI → (verified by page existence; layout is in HTML/CSS)
"""
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "test1145pw!"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _require_engine():
    if _engine is None:
        pytest.skip(
            "DATABASE_URL_UAT not set — skipping Postgres-specific test")


@pytest.fixture(scope="session", autouse=True)
def _wait_for_server():
    import time
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            httpx.get(f"{BASE_URL}/api/auth/me", timeout=2.0)
            return
        except (httpx.ConnectError, httpx.ConnectTimeout):
            time.sleep(1)
    raise RuntimeError(f"Server at {BASE_URL} not ready after 30 s")


@pytest.fixture(scope="module")
def user_id():
    _require_engine()
    name = f"tester1145_{uuid.uuid4().hex[:8]}"
    r = httpx.post(f"{BASE_URL}/api/users", json={"name": name}, timeout=10.0)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture(scope="module")
def auth_client(user_id):
    _require_engine()
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        res = bare.post(
            "/api/auth/login",
            json={"username": name, "password": _TEST_PW},
        )
    assert res.status_code == 200, res.text
    session_cookie = res.cookies.get("session")
    csrf_token = res.cookies.get(CSRF_COOKIE_NAME)
    c = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield c
    c.close()


# ── AC1: Page accessible ────────────────────────────────────────────────

def test_sessions_page_accessible(auth_client):
    """Session entry page is served at /sessions (AC1)."""
    r = auth_client.get("/sessions")
    assert r.status_code == 200, f"GET /sessions returned {r.status_code}"
    assert "text/html" in r.headers.get("content-type", "")


# ── DB schema checks ────────────────────────────────────────────────────

def test_strength_sessions_has_exercise_name_column():
    """strength_sessions has exercise_name column (AC2)."""
    _require_engine()
    inspector = inspect(_engine)
    cols = {c["name"] for c in inspector.get_columns("strength_sessions")}
    assert "exercise_name" in cols, (
        "exercise_name column missing from strength_sessions"
    )


def test_strength_sessions_has_load_unit_column():
    """strength_sessions has load_unit column for weight unit (AC2)."""
    _require_engine()
    inspector = inspect(_engine)
    cols = {c["name"] for c in inspector.get_columns("strength_sessions")}
    assert "load_unit" in cols, (
        "load_unit column missing from strength_sessions"
    )


def test_plyo_sessions_has_exercise_name_column():
    """plyo_sessions has exercise_name column (AC3)."""
    _require_engine()
    inspector = inspect(_engine)
    cols = {c["name"] for c in inspector.get_columns("plyo_sessions")}
    assert "exercise_name" in cols, (
        "exercise_name column missing from plyo_sessions"
    )


# ── AC2: Strength session CRUD ──────────────────────────────────────────

def test_post_strength_session_creates_entry(auth_client):
    """POST /api/strength-sessions creates entry with required fields (AC2)."""
    payload = {
        "session_date": "2099-07-01",
        "exercise_name": "Squat",
        "sets": 3,
        "reps": 5,
        "load": 100.0,
        "load_unit": "kg",
    }
    r = auth_client.post("/api/strength-sessions", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["exercise_name"] == "Squat"
    assert data["sets"] == 3
    assert data["reps"] == 5
    assert float(data["load"]) == 100.0
    assert data["load_unit"] == "kg"
    assert "id" in data
    # cleanup
    auth_client.delete(f"/api/strength-sessions/{data['id']}")


def test_get_strength_sessions_returns_list(auth_client):
    """GET /api/strength-sessions returns persisted entries (AC10)."""
    payload = {
        "session_date": "2099-07-02",
        "exercise_name": "Deadlift",
        "sets": 4,
        "reps": 6,
        "load": 120.0,
        "load_unit": "kg",
    }
    post_r = auth_client.post("/api/strength-sessions", json=payload)
    assert post_r.status_code == 201, post_r.text
    created_id = post_r.json()["id"]

    r = auth_client.get("/api/strength-sessions")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert created_id in ids
    # cleanup
    auth_client.delete(f"/api/strength-sessions/{created_id}")


def test_put_strength_session_updates_entry(auth_client):
    """PUT /api/strength-sessions/{id} updates the load value (AC5, AC8)."""
    payload = {
        "session_date": "2099-07-03",
        "exercise_name": "Bench Press",
        "sets": 3,
        "reps": 8,
        "load": 60.0,
        "load_unit": "kg",
    }
    post_r = auth_client.post("/api/strength-sessions", json=payload)
    assert post_r.status_code == 201
    entry_id = post_r.json()["id"]

    update_r = auth_client.put(
        f"/api/strength-sessions/{entry_id}",
        json={"load": 65.0},
    )
    assert update_r.status_code == 200
    assert float(update_r.json()["load"]) == 65.0
    # cleanup
    auth_client.delete(f"/api/strength-sessions/{entry_id}")


def test_delete_strength_session_removes_entry(auth_client):
    """DELETE /api/strength-sessions/{id} removes the entry (AC6, AC9)."""
    payload = {
        "session_date": "2099-07-04",
        "exercise_name": "Overhead Press",
        "sets": 3,
        "reps": 10,
        "load": 40.0,
        "load_unit": "kg",
    }
    post_r = auth_client.post("/api/strength-sessions", json=payload)
    assert post_r.status_code == 201
    entry_id = post_r.json()["id"]

    del_r = auth_client.delete(f"/api/strength-sessions/{entry_id}")
    assert del_r.status_code == 204

    get_r = auth_client.get("/api/strength-sessions")
    ids = [s["id"] for s in get_r.json()]
    assert entry_id not in ids


def test_multiple_strength_exercises_in_session(auth_client):
    """Multiple exercises with the same date can all be created (AC4)."""
    date = "2099-07-05"
    exercises = [
        {"session_date": date, "exercise_name": "Squat", "sets": 3,
            "reps": 5, "load": 100.0, "load_unit": "kg"},
        {"session_date": date, "exercise_name": "Deadlift",
            "sets": 3, "reps": 5, "load": 120.0, "load_unit": "kg"},
        {"session_date": date, "exercise_name": "Bench",
            "sets": 3, "reps": 5, "load": 80.0, "load_unit": "kg"},
    ]
    ids = []
    for ex in exercises:
        r = auth_client.post("/api/strength-sessions", json=ex)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    get_r = auth_client.get("/api/strength-sessions")
    assert get_r.status_code == 200
    returned_ids = {s["id"] for s in get_r.json()}
    for entry_id in ids:
        assert entry_id in returned_ids
        auth_client.delete(f"/api/strength-sessions/{entry_id}")


# ── AC11: Validation — strength ─────────────────────────────────────────

def test_post_strength_session_requires_session_date(auth_client):
    """POST /api/strength-sessions without session_date returns 422 (AC11)."""
    r = auth_client.post("/api/strength-sessions", json={
        "exercise_name": "Squat",
        "sets": 3,
        "reps": 5,
    })
    assert r.status_code == 422


def test_post_strength_session_requires_exercise_name(auth_client):
    """POST /api/strength-sessions without exercise_name returns 422 (AC11)."""
    r = auth_client.post("/api/strength-sessions", json={
        "session_date": "2099-08-01",
        "sets": 3,
        "reps": 5,
    })
    assert r.status_code == 422


# ── AC3: Plyo session CRUD ──────────────────────────────────────────────

def test_post_plyo_session_creates_entry(auth_client):
    """POST /api/plyo-sessions creates entry with required fields (AC3)."""
    payload = {
        "session_date": "2099-07-10",
        "exercise_name": "Box Jump",
        "foot_contacts": 80,
        "plyo_phase": "build",
    }
    r = auth_client.post("/api/plyo-sessions", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["exercise_name"] == "Box Jump"
    assert data["foot_contacts"] == 80
    assert data["plyo_phase"] == "build"
    assert "id" in data
    auth_client.delete(f"/api/plyo-sessions/{data['id']}")


def test_get_plyo_sessions_returns_list(auth_client):
    """GET /api/plyo-sessions returns persisted entries (AC10)."""
    payload = {
        "session_date": "2099-07-11",
        "exercise_name": "Depth Jump",
        "foot_contacts": 60,
        "plyo_phase": "intro",
    }
    post_r = auth_client.post("/api/plyo-sessions", json=payload)
    assert post_r.status_code == 201
    created_id = post_r.json()["id"]

    r = auth_client.get("/api/plyo-sessions")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert created_id in ids
    auth_client.delete(f"/api/plyo-sessions/{created_id}")


def test_put_plyo_session_updates_entry(auth_client):
    """PUT /api/plyo-sessions/{id} updates foot_contacts (AC5, AC8)."""
    payload = {
        "session_date": "2099-07-12",
        "exercise_name": "Broad Jump",
        "foot_contacts": 40,
        "plyo_phase": "maintain",
    }
    post_r = auth_client.post("/api/plyo-sessions", json=payload)
    assert post_r.status_code == 201
    entry_id = post_r.json()["id"]

    update_r = auth_client.put(
        f"/api/plyo-sessions/{entry_id}",
        json={"foot_contacts": 50},
    )
    assert update_r.status_code == 200
    assert update_r.json()["foot_contacts"] == 50
    auth_client.delete(f"/api/plyo-sessions/{entry_id}")


def test_delete_plyo_session_removes_entry(auth_client):
    """DELETE /api/plyo-sessions/{id} removes the entry (AC6, AC9)."""
    payload = {
        "session_date": "2099-07-13",
        "exercise_name": "Hurdle Hop",
        "foot_contacts": 30,
        "plyo_phase": "intro",
    }
    post_r = auth_client.post("/api/plyo-sessions", json=payload)
    assert post_r.status_code == 201
    entry_id = post_r.json()["id"]

    del_r = auth_client.delete(f"/api/plyo-sessions/{entry_id}")
    assert del_r.status_code == 204

    get_r = auth_client.get("/api/plyo-sessions")
    ids = [s["id"] for s in get_r.json()]
    assert entry_id not in ids


def test_multiple_plyo_exercises_in_session(auth_client):
    """Multiple plyo exercises with the same date can all be created (AC4)."""
    date = "2099-07-14"
    exercises = [
        {"session_date": date, "exercise_name": "Box Jump",
            "foot_contacts": 60, "plyo_phase": "build"},
        {"session_date": date, "exercise_name": "Broad Jump",
            "foot_contacts": 40, "plyo_phase": "build"},
    ]
    ids = []
    for ex in exercises:
        r = auth_client.post("/api/plyo-sessions", json=ex)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    get_r = auth_client.get("/api/plyo-sessions")
    returned_ids = {s["id"] for s in get_r.json()}
    for entry_id in ids:
        assert entry_id in returned_ids
        auth_client.delete(f"/api/plyo-sessions/{entry_id}")


# ── AC11: Validation — plyo ─────────────────────────────────────────────

def test_post_plyo_session_requires_exercise_name(auth_client):
    """POST /api/plyo-sessions without exercise_name returns 422 (AC11)."""
    r = auth_client.post("/api/plyo-sessions", json={
        "session_date": "2099-08-10",
        "foot_contacts": 80,
        "plyo_phase": "build",
    })
    assert r.status_code == 422


def test_post_plyo_session_requires_session_date(auth_client):
    """POST /api/plyo-sessions without session_date returns 422 (AC11)."""
    r = auth_client.post("/api/plyo-sessions", json={
        "exercise_name": "Box Jump",
        "foot_contacts": 80,
        "plyo_phase": "build",
    })
    assert r.status_code == 422


def test_post_plyo_session_requires_foot_contacts(auth_client):
    """POST /api/plyo-sessions without foot_contacts returns 422 (AC11)."""
    r = auth_client.post("/api/plyo-sessions", json={
        "session_date": "2099-08-10",
        "exercise_name": "Box Jump",
        "plyo_phase": "build",
    })
    assert r.status_code == 422


def test_post_plyo_session_requires_valid_phase(auth_client):
    """POST /api/plyo-sessions with invalid plyo_phase returns 422 (AC11)."""
    r = auth_client.post("/api/plyo-sessions", json={
        "session_date": "2099-08-10",
        "exercise_name": "Box Jump",
        "foot_contacts": 80,
        "plyo_phase": "advanced",
    })
    assert r.status_code == 422


# ── Auth: unauthenticated requests blocked ──────────────────────────────

def test_strength_sessions_requires_auth():
    """GET /api/strength-sessions without auth returns 401 (security)."""
    r = httpx.get(f"{BASE_URL}/api/strength-sessions", timeout=10.0)
    assert r.status_code == 401


def test_plyo_sessions_requires_auth():
    """GET /api/plyo-sessions without auth returns 401 (security)."""
    r = httpx.get(f"{BASE_URL}/api/plyo-sessions", timeout=10.0)
    assert r.status_code == 401


# ── Frontend files exist ────────────────────────────────────────────────

def test_sessions_html_exists():
    """frontend/pages/sessions.html exists (AC1, AC12)."""
    p = _ROOT / "frontend" / "pages" / "sessions.html"
    assert p.exists(), f"sessions.html not found at {p}"


def test_sessions_js_exists():
    """frontend/js/sessions.js exists (AC2, AC3)."""
    p = _ROOT / "frontend" / "js" / "sessions.js"
    assert p.exists(), f"sessions.js not found at {p}"
