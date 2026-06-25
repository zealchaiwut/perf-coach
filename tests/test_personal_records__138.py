"""
Tests for issue #138: personal_records table and CRUD API endpoints.
Server under test: http://127.0.0.1:9001
"""
import uuid
from datetime import date, timedelta

import httpx
import pytest
from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "pr-tests-138-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    """Resolve Alice, give her a known password, and log `client` in as her.

    GET /api/personal-records is session-scoped (resolve_user), so the shared
    client must carry Alice's session cookie (httpx persists it). POST/PATCH/
    DELETE still take user_id in the body, so they work regardless of session.
    """
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    with Session(engine) as db:
        db.get(User, uuid.UUID(alice["id"])).password_hash = hash_password(_TEST_PASSWORD)
        db.commit()
    login = client.post("/api/auth/login", json={"username": "Alice", "password": _TEST_PASSWORD})
    assert login.status_code == 200, login.text
    return alice["id"]


def _create_pr(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "track_key": kwargs.get("track_key", "bench_1rm"),
        "track_name": kwargs.get("track_name", "Bench 1RM"),
        "track_type": kwargs.get("track_type", "weight"),
        "value_numeric": kwargs.get("value_numeric", 100),
        "achieved_on": kwargs.get("achieved_on", "2026-04-01"),
        "source": kwargs.get("source", None),
    }
    res = client.post("/api/personal-records", json=payload)
    assert res.status_code == 201, f"Failed to create PR: {res.text}"
    return res.json()


def _delete_pr(client, record_id):
    client.delete(f"/api/personal-records/{record_id}")


# ── GET /api/personal-records ────────────────────────────────────────────────

def test_list_prs_returns_200(client, alice_id):
    res = client.get("/api/personal-records")
    assert res.status_code == 200


def test_list_prs_returns_array(client, alice_id):
    res = client.get("/api/personal-records")
    assert isinstance(res.json(), list)


def test_list_prs_seeded_records_present(client, alice_id):
    res = client.get("/api/personal-records")
    records = res.json()
    keys = {r["track_key"] for r in records}
    assert "half_marathon" in keys
    assert "10k" in keys
    assert "squat_1rm" in keys


def test_list_prs_seeded_values(client, alice_id):
    res = client.get("/api/personal-records")
    records = {r["track_key"]: r for r in res.json()}
    assert records["half_marathon"]["value_numeric"] == 6871.0
    assert records["half_marathon"]["achieved_on"] == "2026-01-28"
    assert records["10k"]["value_numeric"] == 3128.0
    assert records["10k"]["achieved_on"] == "2026-02-18"
    assert records["squat_1rm"]["value_numeric"] == 140.0
    assert records["squat_1rm"]["achieved_on"] == "2026-03-04"


def test_list_prs_response_fields(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="test_fields_check")
    res = client.get("/api/personal-records")
    match = next((r for r in res.json() if r["id"] == pr["id"]), None)
    assert match is not None
    for field in ("id", "user_id", "track_key", "track_name", "track_type",
                  "value_numeric", "achieved_on", "source", "created_at", "updated_at"):
        assert field in match, f"Missing field: {field}"
    _delete_pr(client, pr["id"])


def test_list_prs_requires_auth():
    # Session-scoped: an unauthenticated client must be rejected.
    with httpx.Client(base_url=BASE, timeout=10) as anon:
        res = anon.get("/api/personal-records")
    assert res.status_code == 401


# ── POST /api/personal-records ───────────────────────────────────────────────

def test_create_pr_returns_201(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="create_201_test")
    assert pr["track_key"] == "create_201_test"
    assert pr["id"]
    assert pr["created_at"]
    _delete_pr(client, pr["id"])


def test_create_pr_round_trip(client, alice_id):
    pr = _create_pr(
        client, alice_id,
        track_key="bench_1rm",
        track_name="Bench 1RM",
        track_type="weight",
        value_numeric=100,
        achieved_on="2026-04-01",
    )
    res = client.get("/api/personal-records")
    match = next((r for r in res.json() if r["id"] == pr["id"]), None)
    assert match is not None
    assert match["track_key"] == "bench_1rm"
    assert match["track_name"] == "Bench 1RM"
    assert match["track_type"] == "weight"
    assert match["value_numeric"] == 100.0
    assert match["achieved_on"] == "2026-04-01"
    _delete_pr(client, pr["id"])


def test_create_pr_time_type(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="mile_run", track_type="time", value_numeric=240)
    assert pr["track_type"] == "time"
    _delete_pr(client, pr["id"])


def test_create_pr_unknown_user_returns_404(client):
    res = client.post("/api/personal-records", json={
        "user_id": str(uuid.uuid4()),
        "track_key": "ghost",
        "track_name": "Ghost",
        "track_type": "weight",
        "value_numeric": 10,
        "achieved_on": "2026-01-01",
    })
    assert res.status_code == 404


def test_create_pr_invalid_value_numeric_zero_returns_422(client, alice_id):
    res = client.post("/api/personal-records", json={
        "user_id": alice_id,
        "track_key": "zero_test",
        "track_name": "Zero",
        "track_type": "weight",
        "value_numeric": 0,
        "achieved_on": "2026-01-01",
    })
    assert res.status_code == 422


def test_create_pr_negative_value_numeric_returns_422(client, alice_id):
    res = client.post("/api/personal-records", json={
        "user_id": alice_id,
        "track_key": "neg_test",
        "track_name": "Negative",
        "track_type": "weight",
        "value_numeric": -1,
        "achieved_on": "2026-01-01",
    })
    assert res.status_code == 422


def test_create_pr_future_achieved_on_returns_422(client, alice_id):
    tomorrow = str(date.today() + timedelta(days=1))
    res = client.post("/api/personal-records", json={
        "user_id": alice_id,
        "track_key": "future_test",
        "track_name": "Future",
        "track_type": "weight",
        "value_numeric": 100,
        "achieved_on": tomorrow,
    })
    assert res.status_code == 422


def test_create_pr_invalid_track_type_returns_422(client, alice_id):
    res = client.post("/api/personal-records", json={
        "user_id": alice_id,
        "track_key": "bad_type",
        "track_name": "Bad Type",
        "track_type": "reps",
        "value_numeric": 10,
        "achieved_on": "2026-01-01",
    })
    assert res.status_code == 422


# ── PATCH /api/personal-records/{id} ────────────────────────────────────────

def test_patch_pr_value_numeric(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="patch_val_test", value_numeric=100)
    res = client.patch(f"/api/personal-records/{pr['id']}", json={"value_numeric": 105})
    assert res.status_code == 200
    assert res.json()["value_numeric"] == 105.0
    _delete_pr(client, pr["id"])


def test_patch_pr_updated_at_changes(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="patch_ts_test")
    res = client.patch(f"/api/personal-records/{pr['id']}", json={"value_numeric": 110})
    body = res.json()
    assert body["updated_at"] >= body["created_at"]
    _delete_pr(client, pr["id"])


def test_patch_pr_only_updates_specified_fields(client, alice_id):
    pr = _create_pr(
        client, alice_id,
        track_key="patch_partial",
        track_name="Original Name",
        value_numeric=50,
    )
    res = client.patch(f"/api/personal-records/{pr['id']}", json={"value_numeric": 55})
    body = res.json()
    assert body["value_numeric"] == 55.0
    assert body["track_name"] == "Original Name"
    _delete_pr(client, pr["id"])


def test_patch_pr_invalid_track_type_returns_422(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="patch_bad_type")
    res = client.patch(f"/api/personal-records/{pr['id']}", json={"track_type": "reps"})
    assert res.status_code == 422
    _delete_pr(client, pr["id"])


def test_patch_pr_negative_value_returns_422(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="patch_neg_val")
    res = client.patch(f"/api/personal-records/{pr['id']}", json={"value_numeric": -5})
    assert res.status_code == 422
    _delete_pr(client, pr["id"])


def test_patch_pr_future_date_returns_422(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="patch_future_date")
    tomorrow = str(date.today() + timedelta(days=1))
    res = client.patch(f"/api/personal-records/{pr['id']}", json={"achieved_on": tomorrow})
    assert res.status_code == 422
    _delete_pr(client, pr["id"])


def test_patch_pr_404_on_missing(client):
    res = client.patch(f"/api/personal-records/{uuid.uuid4()}", json={"value_numeric": 99})
    assert res.status_code == 404


# ── DELETE /api/personal-records/{id} ───────────────────────────────────────

def test_delete_pr_returns_204(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="delete_me")
    res = client.delete(f"/api/personal-records/{pr['id']}")
    assert res.status_code == 204


def test_delete_pr_removed_from_list(client, alice_id):
    pr = _create_pr(client, alice_id, track_key="delete_list_check")
    client.delete(f"/api/personal-records/{pr['id']}")
    res = client.get("/api/personal-records")
    ids = [r["id"] for r in res.json()]
    assert pr["id"] not in ids


def test_delete_pr_404_on_missing(client):
    res = client.delete(f"/api/personal-records/{uuid.uuid4()}")
    assert res.status_code == 404
