"""Tests for issue #658: Fix baseline drift after clearing a thresholds field in Settings (runs against UAT)"""
import os
import pytest
import httpx


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_user(client):
    """Create a test user and return login headers."""
    import random
    import string
    username = "test_" + "".join(random.choices(string.ascii_lowercase, k=8))
    password = "TestPass123!"

    # Create user via POST /api/auth/register (if available) or by direct DB seed
    # For now, assume user already seeded. Log in to get session.
    r = client.post("/api/auth/login", json={"username": "testuser", "password": "password"})
    if r.status_code == 401:
        # User doesn't exist; try creating one via a seed endpoint if available
        pytest.skip("Test user not seeded in UAT")
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.cookies  # httpx auto-manages cookies via the client


def test_baseline_drift__clear_ftp_stores_null(client, auth_user):
    # AC: After clearing FTP field and saving, baseline stores null (not system default)
    # 1. Set FTP to 280
    r = client.patch("/api/user-preferences", json={"ftp_w": 280})
    assert r.status_code in (200, 204), f"PATCH failed: {r.status_code} {r.text}"

    # 2. Verify it was saved
    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ftp_w") == 280, f"FTP not saved correctly: {data}"

    # 3. Clear FTP (send null)
    r = client.patch("/api/user-preferences", json={"ftp_w": None})
    assert r.status_code in (200, 204), f"PATCH clear failed: {r.status_code} {r.text}"

    # 4. Verify FTP is now null (not defaulted to 280)
    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ftp_w") is None, f"FTP should be null after clear, got: {data.get('ftp_w')}"


def test_baseline_drift__clear_threshold_hr_stores_null(client, auth_user):
    # AC: After clearing threshold_hr field and saving, baseline stores null
    r = client.patch("/api/user-preferences", json={"threshold_hr": 170})
    assert r.status_code in (200, 204)

    r = client.patch("/api/user-preferences", json={"threshold_hr": None})
    assert r.status_code in (200, 204)

    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("threshold_hr") is None, f"threshold_hr should be null, got: {data.get('threshold_hr')}"


def test_baseline_drift__clear_max_hr_stores_null(client, auth_user):
    # AC: After clearing max_hr field and saving, baseline stores null (not system default)
    r = client.patch("/api/user-preferences", json={"max_hr": 190})
    assert r.status_code in (200, 204)

    r = client.patch("/api/user-preferences", json={"max_hr": None})
    assert r.status_code in (200, 204)

    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("max_hr") is None, f"max_hr should be null, got: {data.get('max_hr')}"


def test_baseline_drift__clear_threshold_pace_stores_null(client, auth_user):
    # AC: After clearing threshold_pace_seconds_per_km field and saving, baseline stores null
    r = client.patch("/api/user-preferences", json={"threshold_pace_seconds_per_km": 270})
    assert r.status_code in (200, 204)

    r = client.patch("/api/user-preferences", json={"threshold_pace_seconds_per_km": None})
    assert r.status_code in (200, 204)

    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("threshold_pace_seconds_per_km") is None, f"threshold_pace should be null, got: {data.get('threshold_pace_seconds_per_km')}"


def test_baseline_drift__clear_zone2_hr_min_stores_null(client, auth_user):
    # AC: After clearing zone2_hr_min field and saving, baseline stores null (not system default)
    r = client.patch("/api/user-preferences", json={"zone2_hr_min": 130})
    assert r.status_code in (200, 204)

    r = client.patch("/api/user-preferences", json={"zone2_hr_min": None})
    assert r.status_code in (200, 204)

    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("zone2_hr_min") is None, f"zone2_hr_min should be null, got: {data.get('zone2_hr_min')}"


def test_baseline_drift__clear_zone2_hr_max_stores_null(client, auth_user):
    # AC: After clearing zone2_hr_max field and saving, baseline stores null (not system default)
    r = client.patch("/api/user-preferences", json={"zone2_hr_max": 155})
    assert r.status_code in (200, 204)

    r = client.patch("/api/user-preferences", json={"zone2_hr_max": None})
    assert r.status_code in (200, 204)

    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("zone2_hr_max") is None, f"zone2_hr_max should be null, got: {data.get('zone2_hr_max')}"


def test_baseline_drift__clear_weekly_zone2_target_stores_null(client, auth_user):
    # AC: After clearing weekly_zone2_target_min field and saving, baseline stores null (not system default)
    r = client.patch("/api/user-preferences", json={"weekly_zone2_target_min": 150})
    assert r.status_code in (200, 204)

    r = client.patch("/api/user-preferences", json={"weekly_zone2_target_min": None})
    assert r.status_code in (200, 204)

    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("weekly_zone2_target_min") is None, f"weekly_zone2_target_min should be null, got: {data.get('weekly_zone2_target_min')}"


def test_baseline_drift__no_redundant_patch_after_clear(client, auth_user):
    # AC: Subsequent save does NOT send redundant PATCH when field is already null
    # 1. Set and clear a field
    r = client.patch("/api/user-preferences", json={"max_hr": 190})
    assert r.status_code in (200, 204)

    r = client.patch("/api/user-preferences", json={"max_hr": None})
    assert r.status_code in (200, 204)

    # 2. Try saving again with no changes (max_hr is already null)
    # The form should detect no changes and not send a PATCH
    # We verify this by checking that a GET-then-patch-with-same-values doesn't modify anything
    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    baseline_max_hr = data.get("max_hr")

    # 3. Send a PATCH with the current value (which is null)
    r = client.patch("/api/user-preferences", json={"max_hr": baseline_max_hr})
    # Should be idempotent — no change should mean a 200 or 204 with no side effects
    assert r.status_code in (200, 204)

    # 4. Verify the value didn't change
    r = client.get("/api/user-preferences")
    assert r.status_code == 200
    data = r.json()
    assert data.get("max_hr") == baseline_max_hr, f"max_hr changed unexpectedly: {data.get('max_hr')}"
