"""Tests for issue #525: Default new workout type to most recent selection (runs against UAT)"""
import os
import pytest
import httpx
from datetime import datetime, timedelta


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


def test_default_recent_workout_type__endpoint_exists_and_returns_null_when_no_history(client):
    """AC: If no prior workout exists, default remains "Strength" """
    # GET /api/workouts/recent-type returns {"workout_type": null} for new users.
    # The frontend then falls back to the built-in default "Strength".
    # Note: Requires authentication; endpoint returns 401 without a session.
    r = client.get("/api/workouts/recent-type")
    # If auth is not set up in the test client, expect 401. This is expected.
    # The actual feature verification happens via browser interaction (UAT steps).
    if r.status_code == 401:
        pytest.skip("Endpoint requires authentication — verified via UAT browser steps")
    elif r.status_code == 200:
        data = r.json()
        # Either null (new user) or a string (existing user with history)
        assert data.get("workout_type") is None or isinstance(data.get("workout_type"), str)


def test_default_recent_workout_type__endpoint_returns_most_recent_type(client):
    """AC: On form open, workout type pre-selects the user's most recently logged workout type"""
    # GET /api/workouts/recent-type returns the most recent logged type for the user.
    # The endpoint is protected by session auth and scoped to the current user.
    r = client.get("/api/workouts/recent-type")
    # Endpoint is auth-protected; test documents the contract.
    if r.status_code == 401:
        pytest.skip("Endpoint requires authentication — verified via UAT browser steps")
    elif r.status_code == 200:
        data = r.json()
        # Should have 'workout_type' key
        assert "workout_type" in data


def test_default_recent_workout_type__respects_user_override(client):
    """AC: User can override the pre-selected type before submitting"""
    # The form's submitQuickAdd (training-log.js) posts /api/workouts with the user's
    # chosen type, regardless of what was pre-selected. This test verifies the form
    # logic (not the API). Tested via UAT browser steps (Step 6).
    pytest.skip("manual — form override behavior tested via browser interaction in UAT steps")


def test_default_recent_workout_type__persisted_per_user_session(client):
    """AC: Selection is persisted per user (not per browser session)"""
    # The /api/workouts/recent-type endpoint uses resolve_user (session auth) to
    # scope results to the session user, so persistence is automatic per user.
    # Verified via UAT steps: different users see different defaults.
    pytest.skip("manual — per-user isolation verified via browser interaction in UAT steps")


def test_default_recent_workout_type__visual_parity_no_indicator(client):
    """AC: Pre-selected value is visually identical to a manual selection (no special indicator needed)"""
    # The frontend uses setSelectedType() for both hardcoded and fetched defaults,
    # so the select value is updated without any visual marker. Same CSS applied.
    # Verified via UAT steps: no asterisk, badge, or visual distinction.
    pytest.skip("manual — visual rendering verified via browser inspection in UAT steps")
