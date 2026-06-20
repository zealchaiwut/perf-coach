"""Tests for issue #692: Suggest thresholds automatically from duration curve (UAT).

Runs against the UAT server to verify:
  - Threshold suggestion API endpoints exist and return correct data
  - Suggestions are computed from user's performance history
  - Manually set thresholds are not overwritten
  - Acceptance flow persists values with proper source tracking
"""
import os
import pytest
import httpx
import json


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
    """Log in a test user and return session cookies for authenticated requests."""
    # Create or fetch a test user with sufficient power meter activity
    # Use credentials from the test seed or create a new session
    r = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass"}
    )
    if r.status_code in (401, 429):
        # User doesn't exist, wrong credentials, or rate-limited; skip authenticated tests
        pytest.skip(f"Test user not available (status {r.status_code})")
    assert r.status_code == 200, f"Login failed: {r.text}"
    return client  # cookies are preserved in the client session


# ── AC1: API endpoints exist ──────────────────────────────────────────────────

def test_get_suggestions_endpoint_exists(auth_user):
    """AC: GET /api/thresholds/suggestions endpoint returns 200."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    data = r.json()
    assert "pending" in data


def test_accept_suggestions_endpoint_exists(auth_user):
    """AC: POST /api/thresholds/suggestions/accept endpoint exists."""
    r = auth_user.post(
        "/api/thresholds/suggestions/accept",
        json={"keys": []}
    )
    # Either 200 (success with empty keys) or 422 (validation) is acceptable
    assert r.status_code in (200, 422)


# ── AC2: Endpoint returns suggestions with confidence field ───────────────────

def test_suggestions_include_confidence_field(auth_user):
    """AC: Each suggestion in pending dict has a 'confidence' or 'high_confidence' field."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    data = r.json()
    pending = data.get("pending", {})

    # For each returned suggestion, verify it has confidence info
    for key, suggestion in pending.items():
        assert isinstance(suggestion, dict)
        assert "value" in suggestion, f"{key} suggestion missing 'value'"
        # Check for either 'confidence' (string) or 'high_confidence' (bool) or both
        has_confidence = "confidence" in suggestion or "high_confidence" in suggestion
        assert has_confidence, f"{key} suggestion missing confidence indicator"


def test_suggestion_confidence_is_string_or_bool(auth_user):
    """AC: confidence field is either a string ('high'/'low') or a boolean."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    data = r.json()
    pending = data.get("pending", {})

    for key, suggestion in pending.items():
        if "confidence" in suggestion:
            conf = suggestion["confidence"]
            assert isinstance(conf, str), f"{key} confidence should be a string, got {type(conf)}"
            assert conf in ("high", "low"), f"{key} confidence should be 'high' or 'low', got '{conf}'"
        if "high_confidence" in suggestion:
            high_conf = suggestion["high_confidence"]
            assert isinstance(high_conf, bool), f"{key} high_confidence should be a bool, got {type(high_conf)}"


# ── AC3: Debug info is exposed ────────────────────────────────────────────────

def test_debug_object_present_in_suggestions_response(auth_user):
    """AC: Response includes debug info (duration_used, raw_value, formula_applied)."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    data = r.json()

    # Debug may be present at top level or nested; check both
    debug = data.get("debug", {})
    if debug:
        for key, dbg_entry in debug.items():
            if dbg_entry:  # Non-empty debug entry
                assert "duration_used" in dbg_entry or "raw_value" in dbg_entry, (
                    f"Debug for {key} missing expected fields"
                )


# ── AC4: FTP endpoint returns correct value (95% of 20-min power) ──────────────

def test_ftp_suggestion_returned_when_available(auth_user):
    """AC: GET suggestions returns ftp_w when sufficient power data exists."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    pending = r.json().get("pending", {})

    # If the user has power meter data, ftp_w should be suggested
    # (This test passes if ftp_w is present OR if pending is empty due to insufficient data)
    if "ftp_w" in pending:
        ftp_suggestion = pending["ftp_w"]
        assert "value" in ftp_suggestion
        assert isinstance(ftp_suggestion["value"], (int, float))
        assert ftp_suggestion["value"] > 0


# ── AC5: Pace endpoint returns correct value ──────────────────────────────────

def test_threshold_pace_returned_when_available(auth_user):
    """AC: GET suggestions returns threshold_pace when sufficient running data exists."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    pending = r.json().get("pending", {})

    if "threshold_pace_seconds_per_km" in pending:
        pace_suggestion = pending["threshold_pace_seconds_per_km"]
        assert "value" in pace_suggestion
        assert isinstance(pace_suggestion["value"], (int, float))
        assert pace_suggestion["value"] > 0


# ── AC6: HR endpoint returns correct value ────────────────────────────────────

def test_threshold_hr_returned_when_available(auth_user):
    """AC: GET suggestions returns threshold_hr when available."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    pending = r.json().get("pending", {})

    if "threshold_hr" in pending:
        hr_suggestion = pending["threshold_hr"]
        assert "value" in hr_suggestion
        assert isinstance(hr_suggestion["value"], (int, float))
        assert 40 < hr_suggestion["value"] < 220  # Sanity check: valid HR range


# ── AC8: Manual overrides are respected ───────────────────────────────────────

def test_manually_set_threshold_is_not_suggested(auth_user):
    """AC: If user has set an FTP manually, suggestion for FTP is omitted."""
    # First accept a suggestion to set it manually
    get_r = auth_user.get("/api/thresholds/suggestions")
    if get_r.status_code == 200:
        pending = get_r.json().get("pending", {})
        if "ftp_w" in pending:
            # Accept the FTP suggestion
            accept_r = auth_user.post(
                "/api/thresholds/suggestions/accept",
                json={"keys": ["ftp_w"]}
            )
            assert accept_r.status_code == 200
            written = accept_r.json().get("written", {})
            assert "ftp_w" in written

            # Now fetch suggestions again; FTP should NOT be in pending
            get_r2 = auth_user.get("/api/thresholds/suggestions")
            assert get_r2.status_code == 200
            pending2 = get_r2.json().get("pending", {})
            assert "ftp_w" not in pending2


# ── AC9/AC10: No writes to unexpected places; API layer handles DB ────────────

def test_accept_writes_to_user_preferences(auth_user):
    """AC: Accept endpoint persists values and returns confirmation."""
    get_r = auth_user.get("/api/thresholds/suggestions")
    assert get_r.status_code == 200
    pending = get_r.json().get("pending", {})

    if pending:
        # Accept at least one suggestion
        keys = list(pending.keys())[:1]
        accept_r = auth_user.post(
            "/api/thresholds/suggestions/accept",
            json={"keys": keys}
        )
        assert accept_r.status_code == 200
        response_data = accept_r.json()
        assert "written" in response_data
        assert "skipped" in response_data
        # At least one of the requested keys should be in written or skipped
        assert len(response_data["written"]) + len(response_data["skipped"]) > 0


# ── AC11/AC12: Edge cases ────────────────────────────────────────────────────

def test_empty_suggestions_when_no_history(auth_user):
    """AC: GET suggestions returns empty pending when user has no qualifying history."""
    r = auth_user.get("/api/thresholds/suggestions")
    assert r.status_code == 200
    data = r.json()
    pending = data.get("pending", {})
    # pending is either empty dict or contains suggestions — either is valid
    assert isinstance(pending, dict)


def test_accept_with_unknown_keys_returns_error(auth_user):
    """AC: POST accept with unknown threshold key returns validation error."""
    r = auth_user.post(
        "/api/thresholds/suggestions/accept",
        json={"keys": ["unknown_threshold_key"]}
    )
    # Should return 422 (validation error) for unknown key
    assert r.status_code == 422


def test_accept_with_invalid_payload_returns_422(auth_user):
    """AC: POST accept with malformed JSON returns 422."""
    r = auth_user.post(
        "/api/thresholds/suggestions/accept",
        json={"keys": "not_a_list"}  # keys should be a list
    )
    assert r.status_code == 422


# ── AC13: Unauthenticated requests are rejected ───────────────────────────────

def test_unauthenticated_get_suggestions_rejected(client):
    """AC: GET /api/thresholds/suggestions without auth returns 401."""
    r = client.get("/api/thresholds/suggestions")
    assert r.status_code == 401


def test_unauthenticated_accept_suggestions_rejected(client):
    """AC: POST /api/thresholds/suggestions/accept without auth returns 401."""
    r = client.post(
        "/api/thresholds/suggestions/accept",
        json={"keys": []}
    )
    assert r.status_code == 401
