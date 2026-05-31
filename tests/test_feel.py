"""Tests for issue #233: GET, PATCH, DELETE /api/feel"""
import uuid

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
_RUN = str(uuid.uuid4())[:8]


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    name = f"FeelUser_{_RUN}"
    res = client.post("/api/users", json={"name": name})
    assert res.status_code in (201, 409)
    users = client.get("/api/users").json()
    u = next((u for u in users if u["name"] == name), None)
    assert u is not None
    return u["id"]


@pytest.fixture(scope="module")
def workout_id(client, user_id):
    res = client.post(
        "/api/workouts",
        json={
            "user_id": user_id,
            "workout_date": "2026-01-10",
            "name": f"Workout_{_RUN}",
            "workout_type": "run",
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


@pytest.fixture(scope="module")
def feel_entry_1(client, user_id):
    """Entry on 2026-01-05, with rpe and notes."""
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": "2026-01-05", "rpe_1_to_10": 7, "notes": "good day"},
    )
    assert res.status_code == 201
    return res.json()


@pytest.fixture(scope="module")
def feel_entry_2(client, user_id):
    """Entry on 2026-01-15, notes only."""
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": "2026-01-15", "notes": "tired"},
    )
    assert res.status_code == 201
    return res.json()


@pytest.fixture(scope="module")
def feel_entry_workout(client, user_id, workout_id):
    """Entry linked to a workout."""
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": "2026-01-10", "workout_id": workout_id, "notes": "post-workout"},
    )
    assert res.status_code == 201
    return res.json()


# (a) GET returns entries for user_id
def test_get_feel_returns_entries(client, user_id, feel_entry_1, feel_entry_2):
    res = client.get("/api/feel", params={"user_id": user_id})
    assert res.status_code == 200
    data = res.json()
    assert "entries" in data
    assert "count" in data
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_1["id"] in ids
    assert feel_entry_2["id"] in ids
    assert data["count"] >= 2
    # sorted feel_date DESC
    dates = [e["feel_date"] for e in data["entries"]]
    assert dates == sorted(dates, reverse=True)


# (b) GET filters by date range
def test_get_feel_date_range(client, user_id, feel_entry_1, feel_entry_2, feel_entry_workout):
    res = client.get("/api/feel", params={"user_id": user_id, "from": "2026-01-10", "to": "2026-01-15"})
    assert res.status_code == 200
    data = res.json()
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_2["id"] in ids        # 2026-01-15 — inside range
    assert feel_entry_workout["id"] in ids  # 2026-01-10 — inside range
    assert feel_entry_1["id"] not in ids    # 2026-01-05 — outside range


# (c) GET filters by workout_id
def test_get_feel_workout_filter(client, user_id, workout_id, feel_entry_workout, feel_entry_1):
    res = client.get("/api/feel", params={"user_id": user_id, "workout_id": workout_id})
    assert res.status_code == 200
    data = res.json()
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_workout["id"] in ids
    assert feel_entry_1["id"] not in ids


# (d) GET has_rpe filter
def test_get_feel_has_rpe(client, user_id, feel_entry_1, feel_entry_2):
    res = client.get("/api/feel", params={"user_id": user_id, "has_rpe": "true"})
    assert res.status_code == 200
    data = res.json()
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_1["id"] in ids   # rpe_1_to_10=7
    assert feel_entry_2["id"] not in ids  # no rpe


# (e) PATCH updates a field
def test_patch_feel_updates_field(client, feel_entry_1):
    res = client.patch(f"/api/feel/{feel_entry_1['id']}", json={"notes": "updated notes"})
    assert res.status_code == 200
    data = res.json()
    assert data["notes"] == "updated notes"
    assert data["id"] == feel_entry_1["id"]


# (f) PATCH with feel_date in body returns 422
def test_patch_feel_date_immutable(client, feel_entry_1):
    res = client.patch(f"/api/feel/{feel_entry_1['id']}", json={"feel_date": "2026-06-01"})
    assert res.status_code == 422


# (g) PATCH unknown id returns 404
def test_patch_feel_not_found(client):
    fake_id = str(uuid.uuid4())
    res = client.patch(f"/api/feel/{fake_id}", json={"notes": "ghost"})
    assert res.status_code == 404


# (h) DELETE removes entry
def test_delete_feel(client, user_id, feel_entry_2):
    res = client.delete(f"/api/feel/{feel_entry_2['id']}")
    assert res.status_code == 204
    # confirm gone
    res2 = client.get("/api/feel", params={"user_id": user_id})
    ids = {e["id"] for e in res2.json()["entries"]}
    assert feel_entry_2["id"] not in ids


# (i) DELETE unknown id returns 404
def test_delete_feel_not_found(client):
    fake_id = str(uuid.uuid4())
    res = client.delete(f"/api/feel/{fake_id}")
    assert res.status_code == 404
