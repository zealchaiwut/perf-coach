"""Tests for issue #232: POST /api/feel"""
import uuid

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
_RUN = str(uuid.uuid4())[:8]
FEEL_DATE = "2026-05-15"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    if alice:
        return alice["id"]
    res = client.post("/api/users", json={"name": "Alice"})
    assert res.status_code in (201, 409)
    users = client.get("/api/users").json()
    alice = next((u for u in users if u["name"] == "Alice"), None)
    assert alice is not None
    return alice["id"]


@pytest.fixture(scope="module")
def other_user_id(client):
    name = f"OtherUser_{_RUN}"
    res = client.post("/api/users", json={"name": name})
    assert res.status_code in (201, 409)
    users = client.get("/api/users").json()
    u = next((u for u in users if u["name"] == name), None)
    assert u is not None
    return u["id"]


@pytest.fixture(scope="module")
def workout_id(client, other_user_id):
    res = client.post(
        "/api/workouts",
        json={
            "user_id": other_user_id,
            "workout_date": FEEL_DATE,
            "name": f"TestWorkout_{_RUN}",
            "workout_type": "strength",
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


# (a) valid POST creates row
def test_valid_post_201(client, user_id):
    res = client.post(
        "/api/feel",
        json={
            "user_id": user_id,
            "feel_date": FEEL_DATE,
            "rpe_1_to_10": 7,
            "notes": "Felt strong today",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert uuid.UUID(body["id"])
    assert body["feel_date"] == FEEL_DATE
    assert body["rpe_1_to_10"] == 7
    assert body["notes"] == "Felt strong today"
    assert body["created_at"] is not None


# (b) missing user_id returns 422
def test_missing_user_id_422(client):
    res = client.post(
        "/api/feel",
        json={"feel_date": FEEL_DATE, "rpe_1_to_10": 5},
    )
    assert res.status_code == 422


# (c) unknown user_id returns 404
def test_unknown_user_404(client):
    res = client.post(
        "/api/feel",
        json={
            "user_id": str(uuid.uuid4()),
            "feel_date": FEEL_DATE,
            "rpe_1_to_10": 5,
        },
    )
    assert res.status_code == 404


# (d) future feel_date (2 days ahead) returns 422
def test_future_date_422(client, user_id):
    from datetime import date, timedelta
    future = (date.today() + timedelta(days=2)).isoformat()
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": future, "rpe_1_to_10": 5},
    )
    assert res.status_code == 422


# tomorrow (1 day ahead) is allowed
def test_tomorrow_allowed_201(client, user_id):
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": tomorrow, "rpe_1_to_10": 5},
    )
    assert res.status_code == 201


# (e) RPE out of range returns 422 with field name in details
def test_rpe_out_of_range_422(client, user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": FEEL_DATE, "rpe_1_to_10": 11},
    )
    assert res.status_code == 422
    detail = res.json().get("detail", {})
    assert "rpe_1_to_10" in str(detail)


# (f) workout_id belonging to different user returns 404
def test_workout_different_user_404(client, user_id, workout_id):
    res = client.post(
        "/api/feel",
        json={
            "user_id": user_id,
            "feel_date": FEEL_DATE,
            "workout_id": workout_id,
            "rpe_1_to_10": 5,
        },
    )
    assert res.status_code == 404


# (g) notes > 10,000 chars returns 422
def test_notes_too_long_422(client, user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": FEEL_DATE, "notes": "x" * 10_001},
    )
    assert res.status_code == 422


# (h) both rpe_1_to_10 and notes null returns 422 with specific message
def test_both_null_422(client, user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": FEEL_DATE},
    )
    assert res.status_code == 422
    detail = res.json().get("detail", {})
    assert "At least one of rpe_1_to_10 or notes is required" in str(detail)


# (i) workout_id: null returns 201
def test_workout_id_null_201(client, user_id):
    res = client.post(
        "/api/feel",
        json={
            "user_id": user_id,
            "feel_date": FEEL_DATE,
            "workout_id": None,
            "rpe_1_to_10": 6,
        },
    )
    assert res.status_code == 201
    assert res.json()["workout_id"] is None


# multiple entries same user+date allowed (no unique constraint)
def test_duplicate_entries_allowed(client, user_id):
    payload = {"user_id": user_id, "feel_date": FEEL_DATE, "rpe_1_to_10": 4}
    for _ in range(3):
        res = client.post("/api/feel", json=payload)
        assert res.status_code == 201
