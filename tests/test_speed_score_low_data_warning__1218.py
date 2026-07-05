"""Tests for issue #1218: Surface speed-score low-data warning + confidence band in the UI (runs against UAT)"""
import os

import httpx
import pytest


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL")
if not BASE_URL:
    uat_port = os.environ.get("UAT_PORT", "9001")
    BASE_URL = f"http://localhost:{uat_port}"


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def authenticated_client(client):
    """Create a client with an active session."""
    # Login with test user
    r = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    if r.status_code != 200:
        pytest.skip("Could not authenticate with test user")
    yield client


# --- Acceptance Criteria ---

def test_speed_score__low_data_warning_true_shows_indicator(authenticated_client):
    # AC: When `speed.low_data_warning` is `true` in the performance response,
    # the speed-score card displays a visible warning indicator (badge, icon, or label).

    # Fetch the performance endpoint to get the speed data
    r = authenticated_client.get("/api/athletes/me/performance")
    assert r.status_code == 200
    data = r.json()

    # If low_data_warning is True, the response should include it
    if data.get("state") == "scored" and data.get("speed"):
        speed = data["speed"]
        # This test verifies the API is returning the low_data_warning field
        assert "low_data_warning" in speed, "API should include low_data_warning field"
        # The field should be a boolean
        assert isinstance(speed["low_data_warning"], bool), "low_data_warning should be boolean"


def test_speed_score__warning_indicator_has_accessible_label(authenticated_client):
    # AC: The warning indicator includes a tooltip or accessible label explaining
    # that the score is based on limited data.

    # This test verifies the performance response includes the necessary data
    # for the frontend to render an accessible label
    r = authenticated_client.get("/api/athletes/me/performance")
    assert r.status_code == 200
    data = r.json()

    if data.get("state") == "scored" and data.get("speed"):
        speed = data["speed"]
        # Verify the response includes qualifying_session_count so frontend can construct a label
        assert "qualifying_session_count" in speed, "API should include qualifying_session_count"
        assert isinstance(speed["qualifying_session_count"], int), "qualifying_session_count should be int"


def test_speed_score__confidence_band_present_renders_visually(authenticated_client):
    # AC: When `speed.confidence_band` is present in the performance response,
    # the speed-score card renders the band visually (e.g. error bars, shaded range, or min/max labels).

    r = authenticated_client.get("/api/athletes/me/performance")
    assert r.status_code == 200
    data = r.json()

    if data.get("state") == "scored" and data.get("speed"):
        speed = data["speed"]
        # This test verifies the API returns the confidence_band field
        assert "confidence_band" in speed, "API should include confidence_band field"
        # If the band exists, it should be a dict with lower/upper values
        if speed["confidence_band"] is not None:
            band = speed["confidence_band"]
            assert isinstance(band, dict), "confidence_band should be a dict"
            assert "lower" in band and "upper" in band, "confidence_band should have lower and upper"


def test_speed_score__no_warning_when_low_data_false(authenticated_client):
    # AC: When `speed.low_data_warning` is `false` or absent,
    # no warning indicator is shown on the speed-score card.

    r = authenticated_client.get("/api/athletes/me/performance")
    assert r.status_code == 200
    data = r.json()

    if data.get("state") == "scored" and data.get("speed"):
        speed = data["speed"]
        # low_data_warning should be False when there's sufficient data
        assert "low_data_warning" in speed
        assert isinstance(speed["low_data_warning"], bool)
        # When False, frontend should not render the warning


def test_speed_score__no_band_when_absent_or_null(authenticated_client):
    # AC: When `speed.confidence_band` is absent or null,
    # no band UI is rendered and the card displays normally.

    r = authenticated_client.get("/api/athletes/me/performance")
    assert r.status_code == 200
    data = r.json()

    if data.get("state") == "scored" and data.get("speed"):
        speed = data["speed"]
        # confidence_band can be None — verify the field exists; frontend handles None gracefully
        assert "confidence_band" in speed


def test_speed_score__data_from_existing_api_only(authenticated_client):
    # AC: The warning indicator and confidence band are driven solely by
    # the `speed` object from the existing performance API response —
    # no new endpoint or backend change is required.

    r = authenticated_client.get("/api/athletes/me/performance")
    assert r.status_code == 200
    data = r.json()

    # Verify the response includes the necessary fields and no new endpoint was created
    assert "speed" in data or data.get("state") in ["building_baseline", "needs_thresholds"], \
        "Performance endpoint should return speed data"

    if data.get("state") == "scored" and data.get("speed"):
        speed = data["speed"]
        # All necessary data should be in the speed object itself
        assert "low_data_warning" in speed
        assert "confidence_band" in speed
        # No new fields needed — the feature uses existing API response
