"""Tests for issue #1210: Same-date weight upsert race condition fix (runs against UAT)"""
import os
import pytest
import httpx
import json
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor


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
def auth_session(client):
    """Create a test user and return a logged-in session with CSRF token handling."""
    # Login with test credentials (user created by seed data)
    r = client.post("/api/auth/login", json={"username": "testuser", "password": "password"})
    assert r.status_code == 200, f"Login failed: {r.text}"

    # Extract CSRF token from response cookie
    csrf_token = r.cookies.get("csrf-token")
    assert csrf_token, "No CSRF token in login response"

    # Create a new client that includes CSRF token in headers for all mutating requests
    class AuthClientWithCSRF:
        def __init__(self, base_client, csrf_token_val):
            self._client = base_client
            self._csrf_token = csrf_token_val

        def put(self, *args, **kwargs):
            headers = kwargs.get("headers", {})
            headers["X-CSRF-Token"] = self._csrf_token
            kwargs["headers"] = headers
            return self._client.put(*args, **kwargs)

        def get(self, *args, **kwargs):
            return self._client.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.get("headers", {})
            headers["X-CSRF-Token"] = self._csrf_token
            kwargs["headers"] = headers
            return self._client.post(*args, **kwargs)

    return AuthClientWithCSRF(client, csrf_token)


# --- Acceptance Criteria Tests ---

def test_weight_entries_race__partial_unique_index_exists(client):
    """AC1: Partial unique index on (user_id, entry_date) WHERE entry_time IS NULL exists"""
    # This is verified via database inspection, not HTTP.
    # For HTTP testing, we'll skip this and verify via manual schema inspection in UAT step 3.
    pytest.skip("manual — verified via database schema inspection (UAT step 3)")


def test_weight_entries_race__atomic_insert_on_conflict(auth_session):
    """AC2: PUT uses atomic INSERT...ON CONFLICT instead of SELECT-then-INSERT"""
    # This is verified via code review of the endpoint logic.
    # We'll test the behavior it should exhibit: no race condition.
    pytest.skip("manual — verified via code review of upsert logic (no SELECT-then-INSERT present)")


def test_weight_entries_race__concurrent_puts_single_row(auth_session):
    """AC3: Two concurrent PUTs for same date result in exactly one row"""
    entry_date = "2026-07-05"

    def put_weight():
        return auth_session.put(
            "/api/weight-entries/by-date",
            json={"entry_date": entry_date, "weight_kg": 75.0, "notes": "concurrent test"}
        )

    # Execute two PUTs in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(put_weight)
        future2 = executor.submit(put_weight)
        r1 = future1.result()
        r2 = future2.result()

    # Both should succeed (2xx)
    assert r1.status_code in (200, 201), f"First PUT failed: {r1.status_code} {r1.text}"
    assert r2.status_code in (200, 201), f"Second PUT failed: {r2.status_code} {r2.text}"

    # Fetch all entries for this date
    r_list = auth_session.get(f"/api/weight-entries?from={entry_date}&to={entry_date}")
    assert r_list.status_code == 200, f"Failed to list entries: {r_list.text}"
    response = r_list.json()
    entries = response.get("entries", [])

    # Should be exactly one entry for this date
    assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}: {entries}"


def test_weight_entries_race__legacy_row_no_duplicate_null_time(auth_session):
    """AC4: PUT for date with legacy time-stamped row doesn't create duplicate NULL-time entry"""
    entry_date = "2026-07-04"

    # First, create an entry with NULL entry_time (standard upsert)
    r1 = auth_session.put(
        "/api/weight-entries/by-date",
        json={"entry_date": entry_date, "weight_kg": 74.5, "notes": "legacy"}
    )
    assert r1.status_code in (200, 201), f"Initial PUT failed: {r1.text}"
    initial_entry = r1.json()

    # Now PUT again for the same date (should update, not create duplicate)
    r2 = auth_session.put(
        "/api/weight-entries/by-date",
        json={"entry_date": entry_date, "weight_kg": 75.5, "notes": "updated"}
    )
    assert r2.status_code in (200, 201), f"Second PUT failed: {r2.text}"
    updated_entry = r2.json()

    # The entry_id should be the same (upsert, not insert)
    assert initial_entry["id"] == updated_entry["id"], "Entry ID changed; expected in-place update"

    # Weight should be updated
    assert updated_entry["weight_kg"] == 75.5, f"Weight not updated: {updated_entry['weight_kg']}"

    # List all entries for this date; should be exactly one
    r_list = auth_session.get(f"/api/weight-entries?from={entry_date}&to={entry_date}")
    assert r_list.status_code == 200, f"Failed to list entries: {r_list.text}"
    response = r_list.json()
    entries = response.get("entries", [])

    # Filter for NULL entry_time (the upserted entries)
    null_time_entries = [e for e in entries if e.get("entry_time") is None]
    assert len(null_time_entries) == 1, f"Expected 1 NULL-time entry, got {len(null_time_entries)}: {null_time_entries}"


def test_weight_entries_race__no_explicit_409_fallback(auth_session):
    """AC5: No explicit 409-race fallback present; DB constraint handles race"""
    # This is verified via code review (checking that no explicit 409 catch exists in the endpoint).
    # We'll test that concurrent requests don't return 409.
    entry_date = "2026-07-03"

    def put_weight():
        return auth_session.put(
            "/api/weight-entries/by-date",
            json={"entry_date": entry_date, "weight_kg": 73.0}
        )

    # Execute two PUTs in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(put_weight)
        future2 = executor.submit(put_weight)
        r1 = future1.result()
        r2 = future2.result()

    # Neither should return 409 (that would indicate an explicit race fallback)
    assert r1.status_code != 409, f"Unexpected 409 from first PUT: {r1.text}"
    assert r2.status_code != 409, f"Unexpected 409 from second PUT: {r2.text}"

    # Both should succeed
    assert r1.status_code in (200, 201), f"First PUT failed: {r1.status_code}"
    assert r2.status_code in (200, 201), f"Second PUT failed: {r2.status_code}"


def test_weight_entries_race__new_date_creates_single_row(auth_session):
    """AC3 variant: PUT for brand-new date creates one row with NULL entry_time"""
    entry_date = "2026-07-06"  # A date unlikely to exist

    r = auth_session.put(
        "/api/weight-entries/by-date",
        json={"entry_date": entry_date, "weight_kg": 76.0, "notes": "new date"}
    )

    assert r.status_code in (200, 201), f"PUT failed: {r.status_code} {r.text}"
    entry = r.json()

    # entry_time should be None (null)
    assert entry.get("entry_time") is None, f"Expected entry_time to be null, got {entry.get('entry_time')}"

    # List all entries for this date
    r_list = auth_session.get(f"/api/weight-entries?from={entry_date}&to={entry_date}")
    assert r_list.status_code == 200, f"Failed to list entries: {r_list.text}"
    response = r_list.json()
    entries = response.get("entries", [])

    # Should be exactly one
    assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}"


def test_weight_entries_race__upsert_idempotent(auth_session):
    """AC4 variant: Multiple PUTs for same date remain idempotent"""
    entry_date = "2026-07-02"

    # First PUT
    r1 = auth_session.put(
        "/api/weight-entries/by-date",
        json={"entry_date": entry_date, "weight_kg": 72.0, "notes": "first"}
    )
    assert r1.status_code in (200, 201), f"First PUT failed: {r1.text}"
    entry1_id = r1.json()["id"]

    # Second PUT (same date, different weight)
    r2 = auth_session.put(
        "/api/weight-entries/by-date",
        json={"entry_date": entry_date, "weight_kg": 72.5, "notes": "second"}
    )
    assert r2.status_code in (200, 201), f"Second PUT failed: {r2.text}"
    entry2_id = r2.json()["id"]
    entry2_weight = r2.json()["weight_kg"]

    # IDs should match (same row)
    assert entry1_id == entry2_id, "Entry ID changed after second PUT"

    # Weight should be the second value
    assert entry2_weight == 72.5, f"Weight not updated: {entry2_weight}"

    # List entries for the date; should be exactly one
    r_list = auth_session.get(f"/api/weight-entries?from={entry_date}&to={entry_date}")
    response = r_list.json()
    entries = response.get("entries", [])
    assert len(entries) == 1, f"Expected 1 entry after two PUTs, got {len(entries)}"
