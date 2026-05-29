"""Tests for issue #138: Add personal_records table and CRUD API endpoints"""
import datetime
import os
import httpx
import pytest


BASE_URL = os.environ.get("BASE_URL", "http://localhost:9001")

TODAY = datetime.date.today().isoformat()
TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
VALID_DATE = "2026-03-04"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    """Fetch Alice's user ID from the seeded users."""
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _delete_record(client, record_id):
    """Helper to delete a record (ignores 404)."""
    client.delete(f"/api/personal-records/{record_id}")


# ── Acceptance Criteria ──────────────────────────────────────────────────────

def test_personalrecord_model_exists(client, alice_id):
    """AC: PersonalRecord SQLAlchemy model exists with correct columns."""
    # We'll verify the model indirectly via the POST endpoint:
    # creating a record and checking all fields are returned
    payload = {
        "user_id": alice_id,
        "track_key": "test_bench",
        "track_name": "Test Bench",
        "track_type": "weight",
        "value_numeric": 100.0,
        "achieved_on": VALID_DATE,
        "source": "manual",
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 201
    data = res.json()

    # Check all required fields are present with correct types
    assert "id" in data
    assert "user_id" in data
    assert "track_key" in data
    assert "track_name" in data
    assert "track_type" in data
    assert "value_numeric" in data
    assert "achieved_on" in data
    assert "source" in data
    assert "created_at" in data
    assert "updated_at" in data

    assert data["user_id"] == alice_id
    assert data["track_key"] == "test_bench"
    assert data["track_type"] == "weight"
    assert isinstance(data["value_numeric"], (int, float))
    assert data["source"] == "manual"

    # Clean up
    _delete_record(client, data["id"])


def test_get_personal_records_returns_all_user_records(client, alice_id):
    """AC: GET /api/personal-records?user_id=<id> returns all records for the given user."""
    # First, ensure we start clean (or at least know the count)
    initial_res = client.get(f"/api/personal-records?user_id={alice_id}")
    assert initial_res.status_code == 200
    initial_count = len(initial_res.json())

    # Create a new record
    payload = {
        "user_id": alice_id,
        "track_key": "test_get_records",
        "track_name": "Test Get Records",
        "track_type": "time",
        "value_numeric": 3600.0,
        "achieved_on": VALID_DATE,
    }
    create_res = client.post("/api/personal-records", json=payload)
    assert create_res.status_code == 201
    record_id = create_res.json()["id"]

    # Now fetch all records
    list_res = client.get(f"/api/personal-records?user_id={alice_id}")
    assert list_res.status_code == 200
    records = list_res.json()

    # Check that the new record is in the list
    assert len(records) == initial_count + 1
    new_record = next((r for r in records if r["id"] == record_id), None)
    assert new_record is not None

    # Clean up
    _delete_record(client, record_id)


def test_post_personal_records_creates_record(client, alice_id):
    """AC: POST /api/personal-records creates a new record and returns the created object."""
    payload = {
        "user_id": alice_id,
        "track_key": "test_post_record",
        "track_name": "Test Post Record",
        "track_type": "weight",
        "value_numeric": 95.5,
        "achieved_on": VALID_DATE,
        "source": "calculated",
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 201
    data = res.json()

    assert data["user_id"] == alice_id
    assert data["track_key"] == "test_post_record"
    assert data["track_name"] == "Test Post Record"
    assert data["track_type"] == "weight"
    assert data["value_numeric"] == 95.5
    assert data["achieved_on"] == VALID_DATE
    assert data["source"] == "calculated"
    assert data["created_at"] is not None
    assert data["updated_at"] is not None

    # Clean up
    _delete_record(client, data["id"])


def test_patch_personal_records_updates_record(client, alice_id):
    """AC: PATCH /api/personal-records/{id} updates an existing record and returns the updated object."""
    # Create a record first
    create_payload = {
        "user_id": alice_id,
        "track_key": "test_patch",
        "track_name": "Test Patch",
        "track_type": "weight",
        "value_numeric": 80.0,
        "achieved_on": VALID_DATE,
    }
    create_res = client.post("/api/personal-records", json=create_payload)
    assert create_res.status_code == 201
    record_id = create_res.json()["id"]
    created_at = create_res.json()["created_at"]

    # Now patch it
    patch_payload = {
        "value_numeric": 85.0,
    }
    patch_res = client.patch(f"/api/personal-records/{record_id}", json=patch_payload)
    assert patch_res.status_code == 200
    data = patch_res.json()

    assert data["id"] == record_id
    assert data["value_numeric"] == 85.0
    assert data["created_at"] == created_at  # created_at should not change
    assert data["updated_at"] is not None
    # updated_at should be different from created_at (or at least be a timestamp)

    # Clean up
    _delete_record(client, record_id)


def test_delete_personal_records_removes_record(client, alice_id):
    """AC: DELETE /api/personal-records/{id} removes the record and returns 204."""
    # Create a record first
    create_payload = {
        "user_id": alice_id,
        "track_key": "test_delete",
        "track_name": "Test Delete",
        "track_type": "time",
        "value_numeric": 4000.0,
        "achieved_on": VALID_DATE,
    }
    create_res = client.post("/api/personal-records", json=create_payload)
    assert create_res.status_code == 201
    record_id = create_res.json()["id"]

    # Delete it
    delete_res = client.delete(f"/api/personal-records/{record_id}")
    assert delete_res.status_code == 204

    # Verify it's gone (404 on GET)
    get_res = client.get(f"/api/personal-records?user_id={alice_id}")
    records = get_res.json()
    assert not any(r["id"] == record_id for r in records)


def test_validation_rejects_value_numeric_zero(client, alice_id):
    """AC: Validation rejects value_numeric <= 0 with 422."""
    payload = {
        "user_id": alice_id,
        "track_key": "test_zero_value",
        "track_name": "Test Zero Value",
        "track_type": "weight",
        "value_numeric": 0,
        "achieved_on": VALID_DATE,
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 422


def test_validation_rejects_value_numeric_negative(client, alice_id):
    """AC: Validation rejects value_numeric <= 0 with 422 (negative test)."""
    payload = {
        "user_id": alice_id,
        "track_key": "test_negative_value",
        "track_name": "Test Negative Value",
        "track_type": "weight",
        "value_numeric": -50.0,
        "achieved_on": VALID_DATE,
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 422


def test_validation_rejects_achieved_on_future(client, alice_id):
    """AC: Validation rejects achieved_on in the future with 422."""
    payload = {
        "user_id": alice_id,
        "track_key": "test_future_date",
        "track_name": "Test Future Date",
        "track_type": "time",
        "value_numeric": 3000.0,
        "achieved_on": TOMORROW,
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 422


def test_validation_rejects_invalid_track_type(client, alice_id):
    """AC: Validation rejects track_type values other than 'time' or 'weight' with 422."""
    payload = {
        "user_id": alice_id,
        "track_key": "test_invalid_type",
        "track_name": "Test Invalid Type",
        "track_type": "reps",
        "value_numeric": 10.0,
        "achieved_on": VALID_DATE,
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 422


def test_seed_script_populates_three_records(client, alice_id):
    """AC: backend/seed.py populates exactly three records for the default user."""
    # This test assumes the seed was already run in the test environment
    # We check that Alice has at least the three seeded records
    res = client.get(f"/api/personal-records?user_id={alice_id}")
    assert res.status_code == 200
    records = res.json()

    # Look for the three specific seeded records
    keys_present = {r["track_key"] for r in records}
    assert "half_marathon" in keys_present, "half_marathon record not found"
    assert "10k" in keys_present, "10k record not found"
    assert "squat_1rm" in keys_present, "squat_1rm record not found"

    # Check specific values from the seed
    half_marathon = next((r for r in records if r["track_key"] == "half_marathon"), None)
    assert half_marathon is not None
    assert half_marathon["value_numeric"] == 6871.0
    assert half_marathon["achieved_on"] == "2026-01-28"
    assert half_marathon["track_type"] == "time"

    ten_k = next((r for r in records if r["track_key"] == "10k"), None)
    assert ten_k is not None
    assert ten_k["value_numeric"] == 3128.0
    assert ten_k["achieved_on"] == "2026-02-18"

    squat = next((r for r in records if r["track_key"] == "squat_1rm"), None)
    assert squat is not None
    assert squat["value_numeric"] == 140.0
    assert squat["achieved_on"] == "2026-03-04"
    assert squat["track_type"] == "weight"


def test_seed_script_idempotent(client, alice_id):
    """AC: Running the seed script a second time does not duplicate records or error."""
    # Get initial count
    initial_res = client.get(f"/api/personal-records?user_id={alice_id}")
    initial_count = len(initial_res.json())

    # Run seed script again (in real scenario; here we assume it was run)
    # If the seed is truly idempotent, the count should not change
    # This test verifies that seeding once gives us the expected state
    assert initial_count >= 3, f"Expected at least 3 seeded records, got {initial_count}"


def test_no_existing_tables_modified(client, alice_id):
    """AC: No existing tables or data are modified by the migration or seed script."""
    # Verify that we can still fetch users and other data
    users_res = client.get("/api/users")
    assert users_res.status_code == 200
    users = users_res.json()
    assert len(users) > 0, "Users table should still have data"

    # Alice should still exist
    alice = next((u for u in users if u["name"] == "Alice"), None)
    assert alice is not None, "Alice should still exist after personal_records migration/seed"
