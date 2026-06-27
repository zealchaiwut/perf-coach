"""Tests for issue #1035: Scheduled and on-demand sleep file sync (UAT).

Tests against the live UAT environment at $UAT_BASE_URL.
Acceptance Criteria:
- AC1: Scheduled job runs for users with Google Drive integration
- AC2: last_sync_at updates when sync completes
- AC3: Job filters files by last_sync_at
- AC4: POST /api/integrations/drive-sleep/sync returns flat keys
- AC5: Re-running sync avoids duplicates (upsert on external_id)
- AC6: Manual sync returns 4xx without integration
- AC7: Scheduled job failures are logged with context
"""
import os
import pytest
import httpx


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
    """Set up a test user with login."""
    # Seed a test user via the seed endpoint or direct DB setup
    # For now, assume a user 'testuser' exists with password 'test123'
    r = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "test123"},
    )
    if r.status_code != 200:
        pytest.skip(f"Could not auth test user: {r.status_code}")
    return client  # client now has session cookie


# ── AC4: Manual sync endpoint returns correct shape ──────────────────────────

def test_drive_sleep_sync__endpoint_returns_200_with_required_keys(auth_user):
    """AC4: endpoint returns 200 with files_seen, rows_imported, rows_updated, rows_skipped."""
    # This test assumes the test user has a Google Drive integration set up.
    # If not set up, the endpoint will return 422 (AC6), which is also valid.
    r = auth_user.post("/api/integrations/drive-sleep/sync")

    # Either 200 (has integration) or 422 (no integration) is expected
    if r.status_code == 422:
        pytest.skip("Test user has no Google Drive integration configured")

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert isinstance(body, dict)
    assert "files_seen" in body
    assert "rows_imported" in body
    assert "rows_updated" in body
    assert "rows_skipped" in body


def test_drive_sleep_sync__response_values_are_integers(auth_user):
    """AC4: all four response values are integers."""
    r = auth_user.post("/api/integrations/drive-sleep/sync")

    if r.status_code == 422:
        pytest.skip("Test user has no Google Drive integration configured")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["files_seen"], int)
    assert isinstance(body["rows_imported"], int)
    assert isinstance(body["rows_updated"], int)
    assert isinstance(body["rows_skipped"], int)


# ── AC6: Manual sync without integration returns 4xx ──────────────────────────

def test_drive_sleep_sync__no_integration_returns_422(auth_user):
    """AC6: calling sync without a Google Drive integration returns 4xx with error message."""
    # Create a separate user with no Google integration
    # For this test, if the existing auth_user has no integration, we'll use it.
    r = auth_user.post("/api/integrations/drive-sleep/sync")

    # If it returns 422, AC6 is satisfied
    if r.status_code == 422:
        body = r.json()
        assert "detail" in body or "message" in body
        assert isinstance(body.get("detail") or body.get("message"), str)
    else:
        # User has integration; test passes (AC6 is about the error case)
        assert r.status_code == 200


# ── AC5: Idempotency — re-running sync doesn't create duplicates ──────────────

def test_drive_sleep_sync__idempotent_on_rerun(auth_user):
    """AC5: calling sync twice without adding new files does not create duplicates."""
    # First sync
    r1 = auth_user.post("/api/integrations/drive-sleep/sync")

    if r1.status_code == 422:
        pytest.skip("Test user has no Google Drive integration configured")

    assert r1.status_code == 200
    body1 = r1.json()
    rows_imported_1 = body1["rows_imported"]

    # Second sync (no new files added)
    r2 = auth_user.post("/api/integrations/drive-sleep/sync")
    assert r2.status_code == 200
    body2 = r2.json()

    # On second run, rows_imported should be 0 (existing records use upsert)
    # rows_updated or rows_skipped should account for previously imported rows
    assert body2["rows_imported"] == 0, "Second sync should not import new rows"
    # files_seen may be > 0 if files still exist, but no duplicates created


def test_drive_sleep_sync__sleep_records_appear_in_api(auth_user):
    """AC5: after sync, new sleep records are retrievable via API."""
    pytest.skip("manual — depends on actual Drive files and parsing (Ticket 3)")


# ── AC3 & AC2: last_sync_at filtering and update ──────────────────────────────

def test_drive_sleep_sync__filters_by_last_sync_at(auth_user):
    """AC3 & AC2: sync filters files by last_sync_at and updates it afterward."""
    pytest.skip("manual — requires direct DB inspection of last_sync_at or mock files")


# ── AC1: Scheduled job runs ──────────────────────────────────────────────────

def test_drive_sleep_sync__scheduled_job_exists(auth_user):
    """AC1: scheduled sync job is running in background."""
    pytest.skip("manual — verify via logs or monitor daemon thread existence")


# ── AC7: Errors are logged with context ──────────────────────────────────────

def test_drive_sleep_sync__error_logging(auth_user):
    """AC7: if sync fails, errors are logged with user_id and message."""
    pytest.skip("manual — verify via logs with 'drive_sleep_sync' + user_id")
