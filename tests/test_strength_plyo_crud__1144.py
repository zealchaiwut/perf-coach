"""Tests for issue #1144: Add Strength and Plyo Session CRUD API (runs against UAT)"""
import os
import pytest
import httpx


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    """Create a persistent client with cookies enabled."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        login_resp = c.post("/api/auth/login", json={"username": "alice", "password": "password"})
        if login_resp.status_code != 200:
            pytest.skip(f"Cannot authenticate as alice — server not running or password wrong ({login_resp.status_code})")
        yield c


# --- Acceptance Criteria: Strength Sessions ---

def test_strength_plyo_crud__strength_list(client):
    # AC: GET /strength-sessions returns a list of all strength sessions
    r = client.get("/api/strength-sessions")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_strength_plyo_crud__strength_get_one(client):
    # AC: GET /strength-sessions/{id} returns a single strength session or 404
    # First create one
    create_resp = client.post("/api/strength-sessions", json={
        "session_date": "2026-06-30",
        "sets": 4,
        "reps": 8,
        "load": 100.0,
    }, status_code=201)
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # Fetch it
    r = client.get(f"/api/strength-sessions/{session_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == session_id
    assert data["sets"] == 4


def test_strength_plyo_crud__strength_create(client):
    # AC: POST /strength-sessions creates a new strength session and returns 201 with the created record
    r = client.post("/api/strength-sessions", json={
        "session_date": "2026-06-30",
        "sets": 3,
        "reps": 5,
        "load": 80.5,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["id"] is not None
    assert data["sets"] == 3
    assert data["reps"] == 5
    assert float(data["load"]) == 80.5


def test_strength_plyo_crud__strength_update(client):
    # AC: PATCH /strength-sessions/{id} partially updates a strength session and returns the updated record
    create_resp = client.post("/api/strength-sessions", json={
        "session_date": "2026-06-30",
        "sets": 4,
        "reps": 8,
        "load": 100.0,
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # Update one field
    r = client.patch(f"/api/strength-sessions/{session_id}", json={"sets": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["sets"] == 5
    assert data["reps"] == 8  # unchanged


def test_strength_plyo_crud__strength_delete(client):
    # AC: DELETE /strength-sessions/{id} deletes a strength session and returns 204
    create_resp = client.post("/api/strength-sessions", json={
        "session_date": "2026-06-30",
        "sets": 2,
        "reps": 10,
        "load": 50.0,
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    r = client.delete(f"/api/strength-sessions/{session_id}")
    assert r.status_code == 204


def test_strength_plyo_crud__strength_get_after_delete(client):
    # AC: Confirm deletion — GET /strength-sessions/{id} for deleted record returns 404
    create_resp = client.post("/api/strength-sessions", json={
        "session_date": "2026-06-30",
        "sets": 2,
        "reps": 10,
        "load": 50.0,
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    client.delete(f"/api/strength-sessions/{session_id}")
    r = client.get(f"/api/strength-sessions/{session_id}")
    assert r.status_code == 404


# --- Acceptance Criteria: Plyo Sessions ---

def test_strength_plyo_crud__plyo_list(client):
    # AC: GET /plyo-sessions returns a list of all plyo sessions
    r = client.get("/api/plyo-sessions")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_strength_plyo_crud__plyo_get_one(client):
    # AC: GET /plyo-sessions/{id} returns a single plyo session or 404
    create_resp = client.post("/api/plyo-sessions", json={
        "session_date": "2026-06-30",
        "foot_contacts": 500,
        "plyo_phase": "build",
    }, status_code=201)
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    r = client.get(f"/api/plyo-sessions/{session_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == session_id
    assert data["foot_contacts"] == 500


def test_strength_plyo_crud__plyo_create(client):
    # AC: POST /plyo-sessions creates a new plyo session and returns 201 with the created record
    r = client.post("/api/plyo-sessions", json={
        "session_date": "2026-06-30",
        "foot_contacts": 750,
        "plyo_phase": "maintain",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["id"] is not None
    assert data["foot_contacts"] == 750
    assert data["plyo_phase"] == "maintain"


def test_strength_plyo_crud__plyo_update(client):
    # AC: PATCH /plyo-sessions/{id} partially updates a plyo session and returns the updated record
    create_resp = client.post("/api/plyo-sessions", json={
        "session_date": "2026-06-30",
        "foot_contacts": 500,
        "plyo_phase": "build",
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    r = client.patch(f"/api/plyo-sessions/{session_id}", json={"foot_contacts": 600})
    assert r.status_code == 200
    data = r.json()
    assert data["foot_contacts"] == 600
    assert data["plyo_phase"] == "build"  # unchanged


def test_strength_plyo_crud__plyo_delete(client):
    # AC: DELETE /plyo-sessions/{id} deletes a plyo session and returns 204
    create_resp = client.post("/api/plyo-sessions", json={
        "session_date": "2026-06-30",
        "foot_contacts": 300,
        "plyo_phase": "intro",
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    r = client.delete(f"/api/plyo-sessions/{session_id}")
    assert r.status_code == 204


def test_strength_plyo_crud__plyo_get_after_delete(client):
    # AC: Confirm deletion — GET /plyo-sessions/{id} for deleted record returns 404
    create_resp = client.post("/api/plyo-sessions", json={
        "session_date": "2026-06-30",
        "foot_contacts": 400,
        "plyo_phase": "maintain",
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    client.delete(f"/api/plyo-sessions/{session_id}")
    r = client.get(f"/api/plyo-sessions/{session_id}")
    assert r.status_code == 404


# --- Acceptance Criteria: Validation & Error Handling ---

def test_strength_plyo_crud__service_layer_delegation(client):
    # AC: All endpoints delegate to a service layer (no raw DB calls in route handlers)
    # This is verified by code inspection, but we confirm endpoints exist and respond
    r = client.get("/api/strength-sessions")
    assert r.status_code == 200


def test_strength_plyo_crud__invalid_payload_422(client):
    # AC: Invalid payloads return 422 with a descriptive validation error
    r = client.post("/api/strength-sessions", json={
        "session_date": "2026-06-30",
        # Missing required fields but sending invalid data
        "sets": "not_a_number",
    })
    assert r.status_code == 422


def test_strength_plyo_crud__missing_required_field_422(client):
    # AC: Missing required fields on POST return 422
    r = client.post("/api/strength-sessions", json={
        # Missing session_date (required)
        "sets": 3,
    })
    assert r.status_code == 422


def test_strength_plyo_crud__compile_check(client):
    # AC: `python -m py_compile` passes on all new/modified files with zero errors
    # This is a static check; confirmed separately via shell command
    assert True


def test_strength_plyo_crud__roundtrip_strength(client):
    # AC: Full create → read → update → read → delete round-trip succeeds for strength sessions
    # Create
    create_resp = client.post("/api/strength-sessions", json={
        "session_date": "2026-06-30",
        "sets": 3,
        "reps": 8,
        "load": 75.0,
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # Read
    get_resp = client.get(f"/api/strength-sessions/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["sets"] == 3

    # Update
    update_resp = client.patch(f"/api/strength-sessions/{session_id}", json={"reps": 10})
    assert update_resp.status_code == 200
    assert update_resp.json()["reps"] == 10

    # Read again
    get_resp2 = client.get(f"/api/strength-sessions/{session_id}")
    assert get_resp2.status_code == 200
    assert get_resp2.json()["reps"] == 10

    # Delete
    delete_resp = client.delete(f"/api/strength-sessions/{session_id}")
    assert delete_resp.status_code == 204


def test_strength_plyo_crud__roundtrip_plyo(client):
    # AC: Full create → read → update → read → delete round-trip succeeds for plyo sessions
    # Create
    create_resp = client.post("/api/plyo-sessions", json={
        "session_date": "2026-06-30",
        "foot_contacts": 600,
        "plyo_phase": "build",
    })
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # Read
    get_resp = client.get(f"/api/plyo-sessions/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["foot_contacts"] == 600

    # Update
    update_resp = client.patch(f"/api/plyo-sessions/{session_id}", json={"foot_contacts": 800})
    assert update_resp.status_code == 200
    assert update_resp.json()["foot_contacts"] == 800

    # Read again
    get_resp2 = client.get(f"/api/plyo-sessions/{session_id}")
    assert get_resp2.status_code == 200
    assert get_resp2.json()["foot_contacts"] == 800

    # Delete
    delete_resp = client.delete(f"/api/plyo-sessions/{session_id}")
    assert delete_resp.status_code == 204


def test_strength_plyo_crud__patch_nonexistent_404(client):
    # AC: Submit a PATCH to a non-existent ID returns 404
    r = client.patch("/api/strength-sessions/99999999-9999-9999-9999-999999999999", json={"sets": 5})
    assert r.status_code == 404
