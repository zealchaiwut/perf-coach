"""Tests for issue #1196: Session submit is non-atomic; partial save on per-exercise POST failure.

Acceptance criteria:
- AC1: submitForm() sends all exercises in a single batched POST request
        → POST /api/strength-sessions/batch and POST /api/plyo-sessions/batch exist
- AC2: Server processes batched request atomically — if any exercise fails, none are saved
        → invalid exercise in batch → 422, nothing persisted
- AC3: Specific error message on failure (not generic "Save failed")
        → error response has a 'detail' field the frontend can render
- AC4: If batch succeeds, all exercises are persisted
        → POST batch with N exercises → GET returns all N
- AC5: No partial state after failed submission
        → after a failed batch, DB is in pre-submission state
- AC6: Existing success path (individual POST) continues to work without regression
"""
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "test1196pw!"
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _require_engine():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping live-server test")


@pytest.fixture(scope="module")
def user_id():
    _require_engine()
    uid = uuid.uuid4()
    name = f"tester1196_{uid.hex[:8]}"
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = _UserModel(id=uid, name=name, password_hash=pw_hash)
        db.add(u)
        db.commit()
    yield str(uid)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uid)
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture(scope="module")
def client(user_id):
    _require_engine()
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        res = bare.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, f"Login failed: {res.text}"
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


# ── AC1: Batch endpoint exists and accepts an array ───────────────────────────

def test_batch_strength_endpoint_exists(client):
    """POST /api/strength-sessions/batch with valid data returns 201 (AC1)."""
    r = client.post("/api/strength-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-01", "exercise_name": "Squat", "sets": 3, "reps": 8},
        ]
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["exercise_name"] == "Squat"
    for item in data:
        client.delete(f"/api/strength-sessions/{item['id']}")


def test_batch_plyo_endpoint_exists(client):
    """POST /api/plyo-sessions/batch with valid data returns 201 (AC1)."""
    r = client.post("/api/plyo-sessions/batch", json={
        "exercises": [
            {
                "session_date": "2099-07-10",
                "exercise_name": "Box Jump",
                "foot_contacts": 80,
                "plyo_phase": "build",
            }
        ]
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["exercise_name"] == "Box Jump"
    client.delete(f"/api/plyo-sessions/{data[0]['id']}")


# ── AC4: All exercises persisted on success ───────────────────────────────────

def test_batch_strength_creates_all_exercises(client):
    """All exercises in the batch are persisted on success (AC4)."""
    r = client.post("/api/strength-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-02", "exercise_name": "Squat", "sets": 3, "reps": 8, "load": 100.0},
            {"session_date": "2099-07-02", "exercise_name": "Deadlift", "sets": 4, "reps": 5, "load": 120.0},
            {"session_date": "2099-07-02", "exercise_name": "Bench Press", "sets": 3, "reps": 10, "load": 80.0},
        ]
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert len(data) == 3
    names = {item["exercise_name"] for item in data}
    assert names == {"Squat", "Deadlift", "Bench Press"}
    for item in data:
        client.delete(f"/api/strength-sessions/{item['id']}")


def test_batch_strength_result_appears_in_list(client):
    """After a successful batch POST, all exercises appear in GET /api/strength-sessions (AC4)."""
    r = client.post("/api/strength-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-03", "exercise_name": "Lunge", "sets": 3, "reps": 12},
            {"session_date": "2099-07-03", "exercise_name": "Split Squat", "sets": 3, "reps": 10},
        ]
    })
    assert r.status_code == 201, r.text
    created_ids = {item["id"] for item in r.json()}

    list_r = client.get("/api/strength-sessions")
    assert list_r.status_code == 200
    all_ids = {s["id"] for s in list_r.json()}
    assert created_ids.issubset(all_ids), f"Batch results not in list: {created_ids - all_ids}"

    for eid in created_ids:
        client.delete(f"/api/strength-sessions/{eid}")


def test_batch_plyo_creates_all_exercises(client):
    """All plyo exercises in the batch are persisted on success (AC4)."""
    r = client.post("/api/plyo-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-11", "exercise_name": "Box Jump", "foot_contacts": 80, "plyo_phase": "build"},
            {"session_date": "2099-07-11", "exercise_name": "Broad Jump", "foot_contacts": 60, "plyo_phase": "build"},
        ]
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert len(data) == 2
    for item in data:
        client.delete(f"/api/plyo-sessions/{item['id']}")


# ── AC2 + AC5: Atomicity — invalid exercise rejects whole batch ───────────────

def test_batch_strength_atomic_negative_sets(client):
    """Batch with a negative-sets exercise is rejected; nothing persisted (AC2, AC5)."""
    before = {s["id"] for s in client.get("/api/strength-sessions").json()}

    r = client.post("/api/strength-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-04", "exercise_name": "Valid Squat", "sets": 3, "reps": 8},
            {"session_date": "2099-07-04", "exercise_name": "Bad Exercise", "sets": -1, "reps": 5},
        ]
    })
    assert r.status_code in (400, 422), f"Expected error, got {r.status_code}: {r.text}"

    after = {s["id"] for s in client.get("/api/strength-sessions").json()}
    assert after == before, f"Partial save occurred: {after - before}"


def test_batch_strength_atomic_missing_exercise_name(client):
    """Batch where one exercise is missing exercise_name is rejected atomically (AC2, AC5)."""
    before = {s["id"] for s in client.get("/api/strength-sessions").json()}

    r = client.post("/api/strength-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-05", "exercise_name": "Overhead Press", "sets": 3},
            {"session_date": "2099-07-05"},  # missing exercise_name (required)
        ]
    })
    assert r.status_code in (400, 422), f"Expected error, got {r.status_code}: {r.text}"

    after = {s["id"] for s in client.get("/api/strength-sessions").json()}
    assert after == before, f"Unexpected new IDs in DB: {after - before}"


def test_batch_plyo_atomic_negative_foot_contacts(client):
    """Plyo batch with negative foot_contacts is rejected atomically (AC2, AC5)."""
    before = {s["id"] for s in client.get("/api/plyo-sessions").json()}

    r = client.post("/api/plyo-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-12", "exercise_name": "Box Jump", "foot_contacts": 80, "plyo_phase": "build"},
            {"session_date": "2099-07-12", "exercise_name": "Bad", "foot_contacts": -10, "plyo_phase": "build"},
        ]
    })
    assert r.status_code in (400, 422), f"Expected error, got {r.status_code}: {r.text}"

    after = {s["id"] for s in client.get("/api/plyo-sessions").json()}
    assert after == before, f"Partial plyo save occurred: {after - before}"


def test_batch_plyo_atomic_invalid_phase(client):
    """Plyo batch with invalid plyo_phase is rejected atomically (AC2, AC5)."""
    before = {s["id"] for s in client.get("/api/plyo-sessions").json()}

    r = client.post("/api/plyo-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-13", "exercise_name": "Hurdle Hop",
             "foot_contacts": 60, "plyo_phase": "build"},
            {"session_date": "2099-07-13", "exercise_name": "Bad Phase",
             "foot_contacts": 40, "plyo_phase": "invalid_phase"},
        ]
    })
    assert r.status_code in (400, 422)

    after = {s["id"] for s in client.get("/api/plyo-sessions").json()}
    assert after == before, f"Partial plyo save occurred: {after - before}"


# ── AC3: Error response has a descriptive detail field ───────────────────────

def test_batch_strength_error_response_has_detail(client):
    """Failed batch response includes a 'detail' field for the frontend to display (AC3)."""
    r = client.post("/api/strength-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-06", "exercise_name": "bad", "sets": -99},
        ]
    })
    assert r.status_code in (400, 422)
    body = r.json()
    assert "detail" in body, f"No 'detail' key in error response: {body}"


def test_batch_plyo_error_response_has_detail(client):
    """Failed plyo batch response includes a 'detail' field (AC3)."""
    r = client.post("/api/plyo-sessions/batch", json={
        "exercises": [
            {"session_date": "2099-07-14", "exercise_name": "box jump", "foot_contacts": -5, "plyo_phase": "build"},
        ]
    })
    assert r.status_code in (400, 422)
    body = r.json()
    assert "detail" in body, f"No 'detail' key in error response: {body}"


# ── AC6: Individual POST endpoints still work (no regression) ─────────────────

def test_individual_strength_post_still_works(client):
    """POST /api/strength-sessions (single-exercise) still returns 201 (AC6)."""
    r = client.post("/api/strength-sessions", json={
        "session_date": "2099-07-07",
        "exercise_name": "Romanian Deadlift",
        "sets": 3,
        "reps": 10,
        "load": 60.0,
    })
    assert r.status_code == 201, r.text
    client.delete(f"/api/strength-sessions/{r.json()['id']}")


def test_individual_plyo_post_still_works(client):
    """POST /api/plyo-sessions (single-exercise) still returns 201 (AC6)."""
    r = client.post("/api/plyo-sessions", json={
        "session_date": "2099-07-15",
        "exercise_name": "Depth Jump",
        "foot_contacts": 50,
        "plyo_phase": "intro",
    })
    assert r.status_code == 201, r.text
    client.delete(f"/api/plyo-sessions/{r.json()['id']}")


# ── Auth: batch endpoints require authentication ──────────────────────────────

def test_batch_strength_requires_auth():
    """POST /api/strength-sessions/batch without auth returns 401 (security)."""
    r = httpx.post(
        f"{BASE_URL}/api/strength-sessions/batch",
        json={"exercises": [{"session_date": "2099-01-01", "exercise_name": "test"}]},
        timeout=10.0,
    )
    assert r.status_code == 401


def test_batch_plyo_requires_auth():
    """POST /api/plyo-sessions/batch without auth returns 401 (security)."""
    r = httpx.post(
        f"{BASE_URL}/api/plyo-sessions/batch",
        json={"exercises": [
            {"session_date": "2099-01-01", "exercise_name": "test",
             "foot_contacts": 10, "plyo_phase": "intro"}
        ]},
        timeout=10.0,
    )
    assert r.status_code == 401


# ── Empty batch handled gracefully ────────────────────────────────────────────

def test_batch_strength_empty_exercises_rejected(client):
    """POST /api/strength-sessions/batch with empty exercises list returns an error."""
    r = client.post("/api/strength-sessions/batch", json={"exercises": []})
    assert r.status_code in (400, 422), f"Expected error for empty batch, got {r.status_code}"
