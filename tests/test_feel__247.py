"""Tests for issue #247: POST /api/feel endpoint for feel entries"""
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_RUN = str(uuid.uuid4())[:8]
FEEL_DATE = "2026-04-20"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    name = f"FeelUser247_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next((u for u in users if u["name"] == name), None)
    assert u is not None
    return u["id"]


@pytest.fixture(scope="module")
def other_user_id(client):
    name = f"OtherUser247_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next((u for u in users if u["name"] == name), None)
    assert u is not None
    return u["id"]


@pytest.fixture(scope="module")
def workout_other_user(client, other_user_id):
    """Workout belonging to other_user — used to test cross-user 404."""
    res = client.post(
        "/api/workouts",
        json={
            "user_id": other_user_id,
            "workout_date": FEEL_DATE,
            "name": f"OtherWorkout247_{_RUN}",
            "workout_type": "run",
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


# (a) valid POST creates row and returns 201 with full dict
def test_valid_post_creates_row(client, user_id):
    res = client.post(
        "/api/feel",
        json={
            "user_id": user_id,
            "feel_date": FEEL_DATE,
            "rpe_1_to_10": 7,
            "notes": "Felt strong",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert uuid.UUID(body["id"])
    assert body["feel_date"] == FEEL_DATE
    assert body["rpe_1_to_10"] == 7
    assert body["notes"] == "Felt strong"
    assert body["created_at"] is not None
    assert "user_id" in body


# (b) missing user_id returns 422
def test_missing_user_id_returns_422(client):
    res = client.post(
        "/api/feel",
        json={"feel_date": FEEL_DATE, "rpe_1_to_10": 5},
    )
    assert res.status_code == 422


# (c) unknown user_id returns 404
def test_unknown_user_id_returns_404(client):
    res = client.post(
        "/api/feel",
        json={
            "user_id": str(uuid.uuid4()),
            "feel_date": FEEL_DATE,
            "rpe_1_to_10": 5,
        },
    )
    assert res.status_code == 404


# (d) feel_date more than 1 day in future returns 422 with "feel_date cannot be in the future"
def test_future_feel_date_returns_422(client, user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": "2099-12-31", "rpe_1_to_10": 5},
    )
    assert res.status_code == 422
    detail = res.json().get("detail", {})
    assert "feel_date cannot be in the future" in str(detail)


# (e) rpe_1_to_10 out of range returns 422 with field name in details
def test_rpe_out_of_range_returns_422(client, user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": FEEL_DATE, "rpe_1_to_10": 11},
    )
    assert res.status_code == 422
    detail = res.json().get("detail", {})
    assert "rpe_1_to_10" in str(detail)


# (f) workout_id belonging to different user returns 404
def test_workout_different_user_returns_404(client, user_id, workout_other_user):
    res = client.post(
        "/api/feel",
        json={
            "user_id": user_id,
            "feel_date": FEEL_DATE,
            "workout_id": workout_other_user,
            "rpe_1_to_10": 5,
        },
    )
    assert res.status_code == 404


# (g) notes longer than 10,000 chars returns 422
def test_notes_too_long_returns_422(client, user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": FEEL_DATE, "notes": "x" * 10_001},
    )
    assert res.status_code == 422


# (h) both rpe_1_to_10 and notes absent returns 422 with specific message
def test_both_rpe_and_notes_null_returns_422(client, user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": FEEL_DATE},
    )
    assert res.status_code == 422
    detail = res.json().get("detail", {})
    assert "At least one of rpe_1_to_10 or notes is required" in str(detail)


# (i) workout_id null is acceptable — entry saves successfully
def test_workout_id_null_saves_successfully(client, user_id):
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


# 5 entries for the same user+date all persist as separate rows
def test_multiple_entries_same_date_allowed(client, user_id):
    payload = {"user_id": user_id, "feel_date": FEEL_DATE, "rpe_1_to_10": 4}
    ids = set()
    for _ in range(5):
        res = client.post("/api/feel", json=payload)
        assert res.status_code == 201
        ids.add(res.json()["id"])
    assert len(ids) == 5
