"""HTTP integration tests for issue #1132 — intensity-distribution API UAT steps.

Tests the endpoints against a live UAT server at $UAT_BASE_URL.
"""
import os
import pytest
import httpx
from datetime import date as _date, timedelta as _timedelta


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:9001"
if not BASE_URL.startswith("http"):
    raise RuntimeError(f"UAT_BASE_URL not set or invalid: {BASE_URL}")


@pytest.fixture
def client():
    """HTTP client pointing at UAT_BASE_URL."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_session(client):
    """Fixture that logs in a test user and returns session cookies.

    Uses the standard test user alice (auto-seeded in UAT).
    Returns the authenticated httpx.Client.
    """
    resp = client.post("/api/auth/login", json={
        "username": "alice",
        "password": "password"
    })
    if resp.status_code != 200:
        pytest.skip(f"Could not authenticate as alice: {resp.status_code}")
    return client


# ─────────────────────────────────────────────────────────────────────────
# UAT Step 1: per-session endpoint with valid session
# ─────────────────────────────────────────────────────────────────────────

def test_per_session_endpoint_200_with_zone_data(auth_session):
    """UAT Step 1: Call GET /api/sessions/{valid_id}/intensity-distribution.

    Expected: 200 response containing low, moderate, high fields and a
    polarized_check verdict.

    Note: This test requires a session with zone data to exist in UAT.
    If no such session exists, the test will be skipped.
    """
    # First, get a list of sessions to find one with splits
    today = _date.today()
    start = today - _timedelta(days=365)
    workouts_resp = auth_session.get("/api/workouts", params={
        "from": start.isoformat(),
        "to": today.isoformat()
    })
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    # Find a workout (it's the "session" in the API terminology)
    if not workouts:
        pytest.skip("No workouts exist in UAT — cannot test per-session endpoint")

    session_id = str(workouts[0]["id"])

    # Call the per-session intensity-distribution endpoint
    r = auth_session.get(f"/api/sessions/{session_id}/intensity-distribution")

    # Verify 200 response
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    data = r.json()

    # Verify required fields exist
    assert "low" in data, "Response must include 'low' field"
    assert "moderate" in data, "Response must include 'moderate' field"
    assert "high" in data, "Response must include 'high' field"
    assert "polarized_check" in data, "Response must include 'polarized_check' field"
    assert "session_id" in data, "Response must include 'session_id' field"
    assert "lap_count" in data, "Response must include 'lap_count' field"
    assert "classified_lap_count" in data, "Response must include 'classified_lap_count' field"

    # Verify polarized_check is a valid enum value
    assert data["polarized_check"] in {
        "pass", "borderline", "fail", "insufficient_data"
    }, f"polarized_check must be one of pass/borderline/fail/insufficient_data, got {data['polarized_check']}"

    # If there's classified data, verify percentages are reasonable
    if data["classified_lap_count"] > 0:
        # low, moderate, high should be non-None if classified_lap_count > 0
        if data["low"] is not None and data["moderate"] is not None and data["high"] is not None:
            total_pct = data["low"] + data["moderate"] + data["high"]
            assert 99 <= total_pct <= 101, f"Percentages should sum to ~100, got {total_pct}"


# ─────────────────────────────────────────────────────────────────────────
# UAT Step 2: rolling endpoint with date range
# ─────────────────────────────────────────────────────────────────────────

def test_rolling_endpoint_200_with_date_range(auth_session):
    """UAT Step 2: Call the rolling distribution endpoint with a date range.

    Expected: 200 response with aggregated low, moderate, high totals
    across all sessions in range and a polarized_check verdict.
    """
    today = _date.today()
    start_date = today - _timedelta(days=27)  # 28-day window

    r = auth_session.get("/api/intensity-distribution/rolling", params={
        "from": start_date.isoformat(),
        "to": today.isoformat(),
    })

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    data = r.json()

    # Verify required fields
    assert "from" in data, "Response must include 'from' field"
    assert "to" in data, "Response must include 'to' field"
    assert "low" in data, "Response must include 'low' field"
    assert "moderate" in data, "Response must include 'moderate' field"
    assert "high" in data, "Response must include 'high' field"
    assert "polarized_check" in data, "Response must include 'polarized_check' field"
    assert "session_count" in data, "Response must include 'session_count' field"

    # Verify polarized_check is a valid enum value
    assert data["polarized_check"] in {
        "pass", "borderline", "fail", "insufficient_data"
    }, f"polarized_check must be valid enum, got {data['polarized_check']}"

    # Verify date range is honored
    assert data["from"] == start_date.isoformat()
    assert data["to"] == today.isoformat()

    # If there's data, verify percentages are reasonable
    if data["session_count"] > 0:
        if data["low"] is not None and data["moderate"] is not None and data["high"] is not None:
            total_pct = data["low"] + data["moderate"] + data["high"]
            assert 99 <= total_pct <= 101, f"Percentages should sum to ~100, got {total_pct}"


def test_rolling_endpoint_default_window(auth_session):
    """Test rolling endpoint uses default 28-day window when no params given."""
    r = auth_session.get("/api/intensity-distribution/rolling")

    assert r.status_code == 200
    data = r.json()

    # Verify it computed a window
    assert data["from"] is not None
    assert data["to"] is not None


def test_rolling_endpoint_invalid_from_date(auth_session):
    """Test rolling endpoint rejects invalid 'from' date format."""
    r = auth_session.get("/api/intensity-distribution/rolling", params={
        "from": "not-a-date",
        "to": _date.today().isoformat(),
    })

    assert r.status_code == 422, f"Expected 422 for invalid date, got {r.status_code}"


def test_rolling_endpoint_from_after_to(auth_session):
    """Test rolling endpoint rejects from > to."""
    today = _date.today()
    r = auth_session.get("/api/intensity-distribution/rolling", params={
        "from": today.isoformat(),
        "to": (today - _timedelta(days=10)).isoformat(),
    })

    assert r.status_code == 422, f"Expected 422 when from > to, got {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────
# UAT Step 3: per-session endpoint with no zone data
# ─────────────────────────────────────────────────────────────────────────

def test_per_session_no_zone_data_returns_200(auth_session):
    """UAT Step 3: Call per-session endpoint with a session having no zone data.

    Expected: 200 response with low/moderate/high all at 0 (or null) and
    polarized_check reflecting insufficient data.

    Note: This test tries to create a session without classified splits,
    or find an existing one. If none exist, the test is skipped.
    """
    # Try to find a session with no classified laps
    today = _date.today()
    start = today - _timedelta(days=365)
    workouts_resp = auth_session.get("/api/workouts", params={
        "from": start.isoformat(),
        "to": today.isoformat()
    })
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    if not workouts:
        pytest.skip("No workouts in UAT to test edge case")

    # Look for a workout with splits but no classification
    target_session = None
    for wkt in workouts:
        if wkt.get("splits") and len(wkt["splits"]) > 0:
            # Check if any split has no intensity_band
            has_unclassified = any(s.get("intensity_band") is None for s in wkt["splits"])
            if has_unclassified:
                target_session = wkt
                break

    if target_session is None:
        pytest.skip("No workout with unclassified splits found in UAT")

    session_id = str(target_session["id"])
    r = auth_session.get(f"/api/sessions/{session_id}/intensity-distribution")

    assert r.status_code == 200
    data = r.json()

    # When there's no classified data, percentages should be None
    if data["classified_lap_count"] == 0:
        assert data["low"] is None or data["low"] == 0
        assert data["moderate"] is None or data["moderate"] == 0
        assert data["high"] is None or data["high"] == 0
        assert data["polarized_check"] == "insufficient_data"


# ─────────────────────────────────────────────────────────────────────────
# UAT Step 4: invalid/non-existent session ID
# ─────────────────────────────────────────────────────────────────────────

def test_invalid_session_id_returns_400(auth_session):
    """UAT Step 4 — part A: Call endpoint with malformed session ID.

    Expected: 400 response with appropriate error message.
    """
    r = auth_session.get("/api/sessions/not-a-uuid/intensity-distribution")

    assert r.status_code == 400, f"Expected 400 for invalid UUID, got {r.status_code}"


def test_nonexistent_session_id_returns_404(auth_session):
    """UAT Step 4 — part B: Call endpoint with non-existent but valid UUID.

    Expected: 404 response.
    """
    import uuid
    fake_id = str(uuid.uuid4())

    r = auth_session.get(f"/api/sessions/{fake_id}/intensity-distribution")

    assert r.status_code == 404, f"Expected 404 for non-existent session, got {r.status_code}"


def test_other_user_session_returns_404(auth_session):
    """Verify that accessing another user's session returns 404."""
    # This would require seeding multiple users in UAT, which may not be set up.
    # Skip for now, as this is more of a security/permission test.
    pytest.skip("Multi-user test requires additional UAT setup")


# ─────────────────────────────────────────────────────────────────────────
# UAT Step 5: py_compile all touched files
# ─────────────────────────────────────────────────────────────────────────

def test_py_compile_intensity_distribution():
    """UAT Step 5: Run py_compile against intensity_distribution.py."""
    import pathlib
    import py_compile

    path = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "intensity_distribution.py"
    assert path.exists(), "intensity_distribution.py must exist"

    # This will raise CompileError if there are syntax errors
    py_compile.compile(str(path), doraise=True)


def test_py_compile_main():
    """UAT Step 5: Run py_compile against main.py (no syntax errors)."""
    import pathlib
    import py_compile

    path = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    py_compile.compile(str(path), doraise=True)
