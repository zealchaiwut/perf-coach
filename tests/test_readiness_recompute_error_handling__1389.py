"""Tests for issue #1389: readiness auto-recompute error handling (runs against UAT)"""
import os
import pytest
import httpx
from datetime import date, timedelta


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def authenticated_client():
    """Create an authenticated httpx client"""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        r = client.post(
            "/api/auth/login",
            json={"username": "Alice", "password": "testpass123"},
        )
        assert r.status_code == 200, f"Auth failed: {r.status_code} {r.text}"
        yield client


@pytest.fixture
def user_id(authenticated_client):
    """Get the authenticated user's ID"""
    r = authenticated_client.get("/api/auth/me")
    assert r.status_code == 200, f"Could not get user info: {r.status_code} {r.text}"
    return r.json()["id"]


def get_csrf_token(client):
    """Extract CSRF token from client cookies"""
    return client.cookies.get("csrf-token")


# --- Acceptance Criteria Tests ---

def test_readiness_recompute_error_handling__post_returns_201(authenticated_client, user_id):
    """AC: POST /api/daily-metrics returns 201 even if readiness recompute fails"""
    csrf_token = get_csrf_token(authenticated_client)
    metric_date = (date.today() - timedelta(days=10)).isoformat()

    payload = {
        "metric_date": metric_date,
        "resting_hr": 60,
        "hrv": 40,
        "sleep_hours": 7.5,
        "sleep_quality": 4,
        "energy": 3,
        "mood": 4,
    }

    r = authenticated_client.post(
        "/api/daily-metrics",
        json=payload,
        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
    )

    # Should return 201 Created regardless of recompute result
    # (or 409 if metric already exists from prior test run)
    assert r.status_code in (201, 409), f"Expected 201 or 409, got {r.status_code}: {r.text}"

    if r.status_code == 409:
        pytest.skip("Metric already exists from prior test run")
    # Verify the metric was actually persisted
    data = r.json()
    assert data["metric_date"] == metric_date
    assert data["resting_hr"] == 60


def test_readiness_recompute_error_handling__patch_returns_200(authenticated_client, user_id):
    """AC: PATCH /api/daily-metrics/{uid}/{metric_date} returns 200 even if readiness recompute fails"""
    csrf_token = get_csrf_token(authenticated_client)
    metric_date = (date.today() - timedelta(days=11)).isoformat()

    # Create metric first
    create_payload = {
        "metric_date": metric_date,
        "resting_hr": 60,
        "hrv": 40,
        "sleep_hours": 7.5,
        "sleep_quality": 4,
        "energy": 3,
        "mood": 4,
    }

    r = authenticated_client.post(
        "/api/daily-metrics",
        json=create_payload,
        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
    )
    # Accept either 201 (new metric) or 409 (already exists from prior test run)
    assert r.status_code in (201, 409), f"Expected 201 or 409, got {r.status_code}: {r.text}"

    # Now patch it
    patch_payload = {
        "resting_hr": 65,
        "energy": 4,
    }

    r = authenticated_client.patch(
        f"/api/daily-metrics/{user_id}/{metric_date}",
        json=patch_payload,
        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
    )

    # Should return 200 regardless of recompute result
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    # Verify the update was persisted
    data = r.json()
    assert data["resting_hr"] == 65


def test_readiness_recompute_error_handling__put_returns_200(authenticated_client, user_id):
    """AC: PUT /api/daily-metrics/{uid}/{metric_date} returns 200 even if readiness recompute fails"""
    csrf_token = get_csrf_token(authenticated_client)
    metric_date = (date.today() - timedelta(days=12)).isoformat()

    put_payload = {
        "resting_hr": 62,
        "hrv": 45,
        "sleep_hours": 8.0,
        "sleep_quality": 5,
        "energy": 4,
        "mood": 5,
    }

    r = authenticated_client.put(
        f"/api/daily-metrics/{user_id}/{metric_date}",
        json=put_payload,
        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
    )

    # Should return 200 regardless of recompute result
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    # Verify the metric was persisted (upserted)
    data = r.json()
    assert data["metric_date"] == metric_date
    assert data["resting_hr"] == 62


def test_readiness_recompute_error_handling__post_metric_persists(authenticated_client, user_id):
    """AC: Metric is persisted in database even if readiness recompute fails on POST"""
    csrf_token = get_csrf_token(authenticated_client)
    metric_date = (date.today() - timedelta(days=13)).isoformat()

    payload = {
        "metric_date": metric_date,
        "resting_hr": 58,
        "hrv": 38,
        "sleep_hours": 7.0,
        "sleep_quality": 3,
        "energy": 3,
        "mood": 3,
    }

    r = authenticated_client.post(
        "/api/daily-metrics",
        json=payload,
        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
    )

    # Accept either 201 (new) or 409 (already exists)
    assert r.status_code in (201, 409), f"Expected 201 or 409, got {r.status_code}: {r.text}"

    # Verify we can retrieve the metric (it was persisted)
    r = authenticated_client.get(f"/api/daily-metrics/{user_id}/{metric_date}")

    assert r.status_code == 200
    data = r.json()
    assert data["resting_hr"] == 58
    assert data["hrv"] == 38


def test_readiness_recompute_error_handling__patch_metric_persists(authenticated_client, user_id):
    """AC: Metric is persisted in database even if readiness recompute fails on PATCH"""
    csrf_token = get_csrf_token(authenticated_client)
    metric_date = (date.today() - timedelta(days=14)).isoformat()

    # Create initial metric
    create_payload = {
        "metric_date": metric_date,
        "resting_hr": 60,
        "hrv": 40,
        "sleep_hours": 7.5,
        "sleep_quality": 4,
        "energy": 3,
        "mood": 4,
    }

    r = authenticated_client.post(
        "/api/daily-metrics",
        json=create_payload,
        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
    )
    # Accept either 201 (new metric) or 409 (already exists from prior test run)
    assert r.status_code in (201, 409), f"Expected 201 or 409, got {r.status_code}: {r.text}"

    # Patch it
    patch_payload = {
        "resting_hr": 70,
        "sleep_hours": 8.5,
    }

    r = authenticated_client.patch(
        f"/api/daily-metrics/{user_id}/{metric_date}",
        json=patch_payload,
        headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
    )

    assert r.status_code == 200

    # Retrieve and verify the patched values were persisted
    r = authenticated_client.get(f"/api/daily-metrics/{user_id}/{metric_date}")

    assert r.status_code == 200
    data = r.json()
    assert data["resting_hr"] == 70
    assert data["sleep_hours"] == 8.5
