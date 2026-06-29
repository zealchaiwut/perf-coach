"""Tests for issue #1053: Show contributing sessions under endurance and speed scores (runs against UAT)"""
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
    """Log in a test user."""
    r_login = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass"},
    )
    if r_login.status_code == 401:
        pytest.skip("Test user not seeded")
    assert r_login.status_code == 200, f"Login failed: {r_login.text}"
    return r_login.json()


# --- Acceptance Criteria ---

def test_contributing_sessions__endpoint_includes_list(client, auth_user):
    # AC: The `GET /api/athletes/{id}/performance` endpoint includes a `contributing_sessions` list
    # on each score object, containing up to five entries.
    user_id = auth_user.get("id", "")
    r = client.get(f"/api/athletes/{user_id}/performance")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    state = data.get("state")

    # If state is 'scored', check contributing_sessions structure
    if state == "scored":
        endurance = data.get("endurance")
        speed = data.get("speed")

        if endurance and isinstance(endurance, dict) and endurance.get("score") is not None:
            assert "contributing_sessions" in endurance, "endurance missing contributing_sessions"
            assert isinstance(endurance["contributing_sessions"], list), "endurance contributing_sessions not a list"
            assert len(endurance["contributing_sessions"]) <= 5, "endurance sessions exceed 5"

        if speed and isinstance(speed, dict) and speed.get("score") is not None:
            assert "contributing_sessions" in speed, "speed missing contributing_sessions"
            assert isinstance(speed["contributing_sessions"], list), "speed contributing_sessions not a list"
            assert len(speed["contributing_sessions"]) <= 5, "speed sessions exceed 5"
    else:
        # For non-scored states (needs_thresholds, building_baseline, error), the endpoint
        # may not include contributing_sessions. This is acceptable per AC.
        pytest.skip(f"Performance endpoint returned state='{state}', not 'scored' — contributing_sessions tested when data is scored")


def test_contributing_sessions__session_dict_has_eight_flat_keys(client, auth_user):
    # AC: Each entry exposes exactly these flat keys: `workout_id`, `date`, `title`,
    # `distance_km`, `pace`, `avg_hr`, `contribution`, `source`.
    user_id = auth_user.get("id", "")
    r = client.get(f"/api/athletes/{user_id}/performance")
    assert r.status_code == 200
    data = r.json()

    if data.get("state") != "scored":
        pytest.skip(f"Performance endpoint returned state='{data.get('state')}', not 'scored'")

    required_keys = {"workout_id", "date", "title", "distance_km", "pace", "avg_hr", "contribution", "source"}

    for score_type in ["endurance", "speed"]:
        score = data.get(score_type)
        if score and isinstance(score, dict) and score.get("score") is not None:
            sessions = score.get("contributing_sessions", [])
            for i, session in enumerate(sessions):
                # Every session must have exactly the 8 required keys
                session_keys = set(session.keys())
                assert session_keys == required_keys, (
                    f"{score_type} session [{i}] has keys {session_keys}, expected {required_keys}"
                )
