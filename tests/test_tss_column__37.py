"""
Tests for issue #37: Add TSS column to workouts with manual input and tss_source flag
Runs against UAT environment
"""
import os
import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _create_workout(client, user_id, *, tss=None, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.get("name", "TSS Test Workout"),
        "workout_date": kwargs.get("workout_date", "2026-05-20"),
        "workout_type": kwargs.get("workout_type", "Running"),
        "exercises": [{"name": "Run", "duration": "30 min"}],
    }
    if tss is not None:
        payload["tss"] = tss
    if "remarks" in kwargs:
        payload["remarks"] = kwargs["remarks"]
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── POST /api/workouts ───────────────────────────────────────────────────────

def test_post_workout_without_tss_returns_null_fields(client, alice_id):
    w = _create_workout(client, alice_id)
    try:
        assert w["tss"] is None
        assert w["tss_source"] is None
    finally:
        _delete_workout(client, w["id"])


def test_post_workout_with_tss_sets_manual_source(client, alice_id):
    w = _create_workout(client, alice_id, tss=85)
    try:
        assert w["tss"] == 85.0
        assert w["tss_source"] == "manual"
    finally:
        _delete_workout(client, w["id"])


def test_post_workout_with_zero_tss_is_valid(client, alice_id):
    w = _create_workout(client, alice_id, tss=0)
    try:
        assert w["tss"] == 0.0
        assert w["tss_source"] == "manual"
    finally:
        _delete_workout(client, w["id"])


def test_post_workout_with_negative_tss_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "name": "Bad TSS",
        "workout_date": "2026-05-20",
        "workout_type": "Running",
        "exercises": [{"name": "Run"}],
        "tss": -5,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422


def test_post_workout_null_tss_leaves_both_null(client, alice_id):
    payload = {
        "user_id": alice_id,
        "name": "Null TSS",
        "workout_date": "2026-05-20",
        "workout_type": "Running",
        "exercises": [{"name": "Run"}],
        "tss": None,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201
    body = res.json()
    try:
        assert body["tss"] is None
        assert body["tss_source"] is None
    finally:
        _delete_workout(client, body["id"])


def test_post_workout_client_tss_source_is_ignored(client, alice_id):
    payload = {
        "user_id": alice_id,
        "name": "Source Override Attempt",
        "workout_date": "2026-05-20",
        "workout_type": "Running",
        "exercises": [{"name": "Run"}],
        "tss": 50,
        "tss_source": "calculated",
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201
    body = res.json()
    try:
        assert body["tss"] == 50.0
        assert body["tss_source"] == "manual"
    finally:
        _delete_workout(client, body["id"])


# ── PATCH /api/workouts/{id} ─────────────────────────────────────────────────

def test_patch_workout_update_tss_sets_manual(client, alice_id):
    w = _create_workout(client, alice_id, tss=85)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"tss": 95})
        assert res.status_code == 200
        body = res.json()
        assert body["tss"] == 95.0
        assert body["tss_source"] == "manual"
    finally:
        _delete_workout(client, w["id"])


def test_patch_workout_null_tss_clears_both_fields(client, alice_id):
    w = _create_workout(client, alice_id, tss=85)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"tss": None})
        assert res.status_code == 200
        body = res.json()
        assert body["tss"] is None
        assert body["tss_source"] is None
    finally:
        _delete_workout(client, w["id"])


def test_patch_workout_omitting_tss_does_not_change_it(client, alice_id):
    w = _create_workout(client, alice_id, tss=85)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"name": "Updated Name"})
        assert res.status_code == 200
        body = res.json()
        assert body["tss"] == 85.0
        assert body["tss_source"] == "manual"
    finally:
        _delete_workout(client, w["id"])


def test_patch_workout_negative_tss_returns_422(client, alice_id):
    w = _create_workout(client, alice_id)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"tss": -1})
        assert res.status_code == 422
    finally:
        _delete_workout(client, w["id"])


# ── GET /api/workouts and GET /api/workouts/{id} ─────────────────────────────

def test_get_workout_returns_tss_fields(client, alice_id):
    w = _create_workout(client, alice_id, tss=100)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        body = res.json()
        assert "tss" in body
        assert "tss_source" in body
        assert body["tss"] == 100.0
        assert body["tss_source"] == "manual"
    finally:
        _delete_workout(client, w["id"])


def test_list_workouts_returns_tss_fields(client, alice_id):
    w = _create_workout(client, alice_id, tss=75, workout_date="2026-05-21")
    try:
        res = client.get(
            "/api/workouts",
            params={"user_id": alice_id, "from": "2026-05-21", "to": "2026-05-21"},
        )
        assert res.status_code == 200
        items = res.json()
        match = next((x for x in items if x["id"] == w["id"]), None)
        assert match is not None
        assert "tss" in match
        assert "tss_source" in match
        assert match["tss"] == 75.0
        assert match["tss_source"] == "manual"
    finally:
        _delete_workout(client, w["id"])


def test_existing_workouts_have_null_tss_after_migration(client, alice_id):
    w = _create_workout(client, alice_id, workout_date="2026-05-22")
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        body = res.json()
        assert body["tss"] is None
        assert body["tss_source"] is None
    finally:
        _delete_workout(client, w["id"])
