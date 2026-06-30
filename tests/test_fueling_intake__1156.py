"""
Tests for issue #1156: Add lightweight fueling/intake input for energy-availability proxy.
Server under test: http://127.0.0.1:9001
"""
import datetime

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TEST_DATE = "2026-01-20"
TEST_DATE_2 = "2026-01-21"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client(client):
    """Authenticated client via session cookie."""
    res = client.post("/api/auth/login", json={"username": "Alice", "password": "password"})
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _delete_metric(client, user_id, metric_date, session_cookie=None):
    cookies = {"session": session_cookie} if session_cookie else {}
    client.delete(f"/api/daily-metrics/{user_id}/{metric_date}", cookies=cookies)


# ── AC: kcal_intake field in POST ─────────────────────────────────────────────

def test_post_creates_row_with_kcal_intake(client, alice_id, auth_client):
    """AC: intake value is persisted to the database."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    payload = {
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "kcal_intake": 2500,
    }
    res = client.post("/api/daily-metrics", json=payload, cookies={"session": session})
    assert res.status_code == 201
    data = res.json()
    assert data["kcal_intake"] == 2500
    _delete_metric(client, alice_id, TEST_DATE, session)


# ── AC: kcal_intake included in GET response ──────────────────────────────────

def test_get_returns_kcal_intake(client, alice_id, auth_client):
    """AC: persisted intake value is retrievable via the API."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    client.post("/api/daily-metrics", json={
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "kcal_intake": 3000,
    }, cookies={"session": session})
    res = client.get(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", cookies={"session": session})
    assert res.status_code == 200
    assert res.json()["kcal_intake"] == 3000
    _delete_metric(client, alice_id, TEST_DATE, session)


def test_list_returns_kcal_intake(client, alice_id, auth_client):
    """AC: list endpoint includes kcal_intake in each row."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    client.post("/api/daily-metrics", json={
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "kcal_intake": 1800,
    }, cookies={"session": session})
    res = client.get("/api/daily-metrics", params={"from": TEST_DATE, "to": TEST_DATE},
                     cookies={"session": session})
    assert res.status_code == 200
    items = res.json()
    match = next((x for x in items if x["metric_date"] == TEST_DATE), None)
    assert match is not None
    assert match["kcal_intake"] == 1800
    _delete_metric(client, alice_id, TEST_DATE, session)


# ── AC: upsert (PUT) updates, not duplicates ──────────────────────────────────

def test_put_upserts_kcal_intake(client, alice_id, auth_client):
    """AC: submitting a new value for same day updates rather than duplicates."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    client.put(f"/api/daily-metrics/{alice_id}/{TEST_DATE}",
               json={"kcal_intake": 2000}, cookies={"session": session})
    res = client.put(f"/api/daily-metrics/{alice_id}/{TEST_DATE}",
                     json={"kcal_intake": 2500}, cookies={"session": session})
    assert res.status_code == 200
    assert res.json()["kcal_intake"] == 2500
    # Confirm only one row exists
    list_res = client.get("/api/daily-metrics",
                          params={"from": TEST_DATE, "to": TEST_DATE},
                          cookies={"session": session})
    rows = [x for x in list_res.json() if x["metric_date"] == TEST_DATE]
    assert len(rows) == 1
    _delete_metric(client, alice_id, TEST_DATE, session)


def test_patch_updates_kcal_intake(client, alice_id, auth_client):
    """AC: PATCH can update kcal_intake without affecting other fields."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    client.post("/api/daily-metrics", json={
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "kcal_intake": 2000,
        "resting_hr": 58,
    }, cookies={"session": session})
    res = client.patch(f"/api/daily-metrics/{alice_id}/{TEST_DATE}",
                       json={"kcal_intake": 2800},
                       cookies={"session": session})
    assert res.status_code == 200
    data = res.json()
    assert data["kcal_intake"] == 2800
    assert data["resting_hr"] == 58
    _delete_metric(client, alice_id, TEST_DATE, session)


# ── AC: null/absent when not provided ─────────────────────────────────────────

def test_kcal_intake_null_when_not_set(client, alice_id, auth_client):
    """AC: no intake record created when field left blank."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    client.post("/api/daily-metrics", json={
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "resting_hr": 60,
    }, cookies={"session": session})
    res = client.get(f"/api/daily-metrics/{alice_id}/{TEST_DATE}", cookies={"session": session})
    assert res.status_code == 200
    assert res.json()["kcal_intake"] is None
    _delete_metric(client, alice_id, TEST_DATE, session)


# ── AC: kcal_intake validation ────────────────────────────────────────────────

def test_negative_kcal_intake_rejected(client, alice_id, auth_client):
    """AC: invalid intake values are rejected with 422."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    res = client.post("/api/daily-metrics", json={
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "kcal_intake": -100,
    }, cookies={"session": session})
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "kcal_intake"


def test_zero_kcal_intake_rejected(client, alice_id, auth_client):
    """AC: zero is not a valid intake value."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    res = client.post("/api/daily-metrics", json={
        "user_id": alice_id,
        "metric_date": TEST_DATE,
        "kcal_intake": 0,
    }, cookies={"session": session})
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "kcal_intake"


# ── AC: kcal_intake appears in API response dict ──────────────────────────────

def test_response_dict_has_kcal_intake_key(client, alice_id, auth_client):
    """AC: kcal_intake key always present in response, even when null."""
    session = auth_client
    _delete_metric(client, alice_id, TEST_DATE, session)
    res = client.post("/api/daily-metrics", json={
        "user_id": alice_id,
        "metric_date": TEST_DATE,
    }, cookies={"session": session})
    assert res.status_code == 201
    assert "kcal_intake" in res.json()
    _delete_metric(client, alice_id, TEST_DATE, session)


# ── AC: py_compile passes ─────────────────────────────────────────────────────

def test_py_compile_main():
    """AC: all new/modified Python files pass py_compile."""
    import py_compile
    import os
    files = [
        os.path.join(os.path.dirname(__file__), '..', 'backend', 'main.py'),
        os.path.join(os.path.dirname(__file__), '..', 'backend', 'models.py'),
    ]
    for f in files:
        py_compile.compile(f, doraise=True)
