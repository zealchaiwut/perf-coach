"""Tests for issue #358: Verify personal_records table + endpoints are fully landed."""
import subprocess
import uuid
from datetime import date, timedelta

import httpx
import pytest
from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy import inspect
from sqlalchemy.orm import Session


BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "pr-tests-358-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found"
    with Session(engine) as db:
        db.get(User, uuid.UUID(alice["id"])).password_hash = hash_password(_TEST_PASSWORD)
        db.commit()
    login = client.post("/api/auth/login", json={"username": "Alice", "password": _TEST_PASSWORD})
    assert login.status_code == 200, login.text
    return alice["id"]


# AC: PersonalRecord model with correct columns
def test_personalrecord_model_has_required_columns():
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("personal_records")}
    required = {
        "id", "user_id", "track_key", "track_name", "track_type",
        "value_numeric", "achieved_on", "source", "created_at", "updated_at",
    }
    missing = required - cols
    assert not missing, f"Missing columns: {missing}"


# AC: alembic upgrade head runs cleanly
def test_alembic_upgrade_head_first_run():
    r = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        capture_output=True, text=True,
        cwd="/Users/chaiwutchaianuchittrakul/dev/perf-coach/coder",
    )
    assert r.returncode == 0, f"alembic upgrade head failed:\n{r.stderr}"


# AC: alembic upgrade head is idempotent (second run also clean)
def test_alembic_upgrade_head_second_run():
    r = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        capture_output=True, text=True,
        cwd="/Users/chaiwutchaianuchittrakul/dev/perf-coach/coder",
    )
    assert r.returncode == 0, f"alembic upgrade head (second run) failed:\n{r.stderr}"


# AC: GET /api/personal-records endpoint exists
def test_get_endpoint_returns_200(client, alice_id):
    res = client.get("/api/personal-records")
    assert res.status_code == 200


# AC: GET returns >= 3 seeded records
def test_get_returns_at_least_3_seeded_records(client, alice_id):
    res = client.get("/api/personal-records")
    records = res.json()
    assert len(records) >= 3
    keys = {r["track_key"] for r in records}
    assert "half_marathon" in keys
    assert "10k" in keys
    assert "squat_1rm" in keys


# AC: Seeded values correct (half_marathon=6871, 10k=3128, squat_1rm=140 weight)
def test_seeded_record_values(client, alice_id):
    res = client.get("/api/personal-records")
    records = {r["track_key"]: r for r in res.json()}
    assert records["half_marathon"]["value_numeric"] == 6871.0
    assert records["10k"]["value_numeric"] == 3128.0
    assert records["squat_1rm"]["value_numeric"] == 140.0
    assert records["squat_1rm"]["track_type"] == "weight"


# AC: POST round-trip creates a record and returns it with a valid UUID
def test_post_round_trip_returns_valid_uuid(client, alice_id):
    payload = {
        "user_id": alice_id,
        "track_key": "test_358_uuid",
        "track_name": "Test 358 UUID",
        "track_type": "time",
        "value_numeric": 1800,
        "achieved_on": "2026-01-01",
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert uuid.UUID(data["id"])  # raises if not valid UUID
    client.delete(f"/api/personal-records/{data['id']}")


# AC: POST validation rejects value_numeric <= 0
def test_post_rejects_zero_value_numeric(client, alice_id):
    res = client.post("/api/personal-records", json={
        "user_id": alice_id, "track_key": "v0_358", "track_name": "Zero",
        "track_type": "weight", "value_numeric": 0, "achieved_on": "2026-01-01",
    })
    assert res.status_code == 422


def test_post_rejects_negative_value_numeric(client, alice_id):
    res = client.post("/api/personal-records", json={
        "user_id": alice_id, "track_key": "vneg_358", "track_name": "Negative",
        "track_type": "weight", "value_numeric": -1, "achieved_on": "2026-01-01",
    })
    assert res.status_code == 422


# AC: POST validation rejects achieved_on in the future
def test_post_rejects_future_achieved_on(client, alice_id):
    tomorrow = str(date.today() + timedelta(days=1))
    res = client.post("/api/personal-records", json={
        "user_id": alice_id, "track_key": "future_358", "track_name": "Future",
        "track_type": "weight", "value_numeric": 100, "achieved_on": tomorrow,
    })
    assert res.status_code == 422


# AC: POST validation rejects track_type outside {time, weight}
def test_post_rejects_invalid_track_type(client, alice_id):
    res = client.post("/api/personal-records", json={
        "user_id": alice_id, "track_key": "badtype_358", "track_name": "BadType",
        "track_type": "distance", "value_numeric": 100, "achieved_on": "2026-01-01",
    })
    assert res.status_code == 422


# AC: PATCH updates a record without destroying other fields
def test_patch_updates_without_destroying_fields(client, alice_id):
    pr = client.post("/api/personal-records", json={
        "user_id": alice_id,
        "track_key": "patch_intact_358",
        "track_name": "Patch Intact 358",
        "track_type": "weight",
        "value_numeric": 100,
        "achieved_on": "2026-01-01",
    }).json()
    res = client.patch(f"/api/personal-records/{pr['id']}", json={"value_numeric": 110})
    assert res.status_code == 200
    data = res.json()
    assert data["value_numeric"] == 110.0
    assert data["track_name"] == "Patch Intact 358"
    assert data["track_key"] == "patch_intact_358"
    assert data["track_type"] == "weight"
    client.delete(f"/api/personal-records/{pr['id']}")


# AC: DELETE removes the record and returns 204
def test_delete_returns_204(client, alice_id):
    pr = client.post("/api/personal-records", json={
        "user_id": alice_id, "track_key": "del_358", "track_name": "Delete 358",
        "track_type": "time", "value_numeric": 500, "achieved_on": "2026-01-01",
    }).json()
    res = client.delete(f"/api/personal-records/{pr['id']}")
    assert res.status_code == 204


def test_delete_removes_record_from_list(client, alice_id):
    pr = client.post("/api/personal-records", json={
        "user_id": alice_id, "track_key": "del2_358", "track_name": "Delete2 358",
        "track_type": "time", "value_numeric": 500, "achieved_on": "2026-01-01",
    }).json()
    client.delete(f"/api/personal-records/{pr['id']}")
    all_records = client.get("/api/personal-records").json()
    assert not any(r["id"] == pr["id"] for r in all_records)


# AC: No existing personal_records rows are destroyed by running remediation
def test_seeded_records_survive_crud_ops(client, alice_id):
    res = client.get("/api/personal-records")
    keys = {r["track_key"] for r in res.json()}
    assert "half_marathon" in keys
    assert "10k" in keys
    assert "squat_1rm" in keys
