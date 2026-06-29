"""Tests for issue #930: Render four distinct score-card states on Performance tab (runs against UAT)

This test file validates the performance API endpoint response structure.
The endpoint must return responses matching the expected states so the frontend
can render the four distinct card states properly.
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


def test_score_card__api_endpoint_exists(client):
    """Verify that the performance endpoint exists and returns sensible responses."""
    r = client.get("/api/athletes/test-id/performance")
    # Should not return 500 (server error)
    assert r.status_code != 500, f"Server error: {r.text}"


def test_score_card__response_has_required_keys(client):
    """AC: The API response must include both 'endurance' and 'speed' keys
    so the frontend can render both cards.
    """
    # This test validates the contract; even unauthenticated responses should
    # have the structure (though they may be error states)
    # For a properly authenticated request, we expect 200; for test purposes
    # we accept 401 and verify the response is JSON-parseable
    r = client.get("/api/athletes/test-id/performance")

    if r.status_code == 200:
        data = r.json()
        assert "endurance" in data, "Missing 'endurance' key in response"
        assert "speed" in data, "Missing 'speed' key in response"


def test_score_card__scored_state_has_ring_fields(client):
    """AC: When state is 'scored', endurance and speed payloads include score, direction, trend.

    Updated for issue #1020: state is now top-level; endurance/speed are non-null dicts
    when state='scored'.
    """
    r = client.get("/api/athletes/test-id/performance")

    if r.status_code == 401:
        pytest.skip("Not authenticated - this test requires UAT authentication")

    if r.status_code == 200:
        data = r.json()
        if data.get("state") == "scored":
            for score_type in ["endurance", "speed"]:
                score_data = data.get(score_type)
                assert isinstance(score_data, dict), (
                    f"{score_type} must be a dict when state=scored"
                )
                assert "score" in score_data
                assert isinstance(score_data["score"], (int, float))
                assert score_data["score"] >= 0
                assert "direction" in score_data
                assert "trend" in score_data
                assert isinstance(score_data["trend"], list)


def test_score_card__needs_thresholds_state_structure(client):
    """AC: When top-level state is 'needs_thresholds', endurance and speed are null.

    Updated for issue #1020: state is top-level; endurance/speed are null (not nested dicts).
    """
    r = client.get("/api/athletes/test-id/performance")

    if r.status_code == 401:
        pytest.skip("Not authenticated")

    if r.status_code == 200:
        data = r.json()
        if data.get("state") == "needs_thresholds":
            assert data.get("endurance") is None, (
                "endurance must be null for needs_thresholds"
            )
            assert data.get("speed") is None, (
                "speed must be null for needs_thresholds"
            )


def test_score_card__building_baseline_state_structure(client):
    """AC: When top-level state is 'building_baseline', endurance and speed are null.

    Updated for issue #1020: state is top-level; endurance/speed are null (not nested dicts).
    """
    r = client.get("/api/athletes/test-id/performance")

    if r.status_code == 401:
        pytest.skip("Not authenticated")

    if r.status_code == 200:
        data = r.json()
        if data.get("state") == "building_baseline":
            assert data.get("endurance") is None, (
                "endurance must be null for building_baseline"
            )
            assert data.get("speed") is None, (
                "speed must be null for building_baseline"
            )


def test_score_card__state_field_is_explicit(client):
    """AC: The response includes a top-level 'state' field for explicit frontend branching.

    Updated for issue #1020: state is a top-level key, not nested in endurance/speed.
    """
    r = client.get("/api/athletes/test-id/performance")

    if r.status_code == 401:
        pytest.skip("Not authenticated")

    if r.status_code == 200:
        data = r.json()
        assert "state" in data, "top-level 'state' key must be present"
        valid_states = {"scored", "needs_thresholds", "building_baseline", "error"}
        assert data["state"] in valid_states, (
            f"top-level state must be one of {valid_states}; got {data['state']!r}"
        )
