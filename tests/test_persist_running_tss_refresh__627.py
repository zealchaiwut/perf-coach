"""Tests for issue #627: persist_running_tss should refresh computed TSS on threshold change (runs against UAT)"""
import os
import pathlib
import uuid
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "test627pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _create_and_login() -> tuple[httpx.Client, str]:
    """Create a test user, set password, and return authenticated client + user_id."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"tss_test_{uuid.uuid4().hex[:8]}"
    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    bare.close()
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]

    # Set password via DB
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    # Login
    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r.status_code == 200, f"login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    client = httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return client, user_id


def _delete_user(user_id: str) -> None:
    """Clean up test user from DB."""
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


@pytest.fixture
def client():
    """Authenticated httpx client for a test user."""
    auth_client, user_id = _create_and_login()
    yield auth_client
    auth_client.close()
    _delete_user(user_id)


@pytest.fixture
def user_with_threshold(client):
    """Ensure user has explicit threshold values set."""
    # PATCH to set user preferences with threshold values
    r = client.patch(
        "/api/user-preferences",
        json={
            "threshold_hr": 170,
            "threshold_pace_seconds_per_km": 330,  # 5:30/km
            "ftp_w": 280,
        },
    )
    # Accept 200 or 201
    assert r.status_code in (200, 201), f"Failed to set preferences: {r.text}"
    return client


# --- Acceptance Criteria (inferred from #582 UAT step 5 and #627 issue) ---

def test_persist_running_tss__computed_tss_refreshes_on_threshold_change(user_with_threshold):
    """AC: When threshold changes, previously-computed TSS is refreshed on next workout fetch.

    Test the specific scenario from #627: create a running workout with computed TSS,
    change the threshold, and verify that the TSS value is refreshed (not left stale).
    """
    client = user_with_threshold
    # Step 1: Create a running workout with workout data but no manual TSS
    r = client.post(
        "/api/workouts",
        json={
            "workout_date": "2026-07-19",
            "name": "Test Run for Threshold Refresh",
            "workout_type": "run",
            "duration_seconds": 3600,  # 1 hour
            "avg_hr": 160,  # Below threshold (170)
            "distance_km": 10.0,
            # tss is intentionally omitted — should be computed
        },
    )
    assert r.status_code in (200, 201), f"Failed to create workout: {r.text}"
    workout = r.json()
    workout_id = workout["id"]

    # Step 2: Fetch the workout and verify computed TSS was persisted
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_v1 = r.json()
    assert "tss" in workout_v1, "Workout response missing tss field"
    assert workout_v1["tss"] is not None, "Computed TSS should not be None"
    assert "tss_method" in workout_v1, "Workout response missing tss_method field"
    assert workout_v1["tss_method"] in ("hr", "pace", "power"), "tss_method should be set"

    initial_tss = workout_v1["tss"]

    # Step 3: Change the pace threshold to a significantly lower value (faster)
    # This makes the pace-based intensity factor smaller, lowering TSS
    r = client.patch(
        "/api/user-preferences",
        json={
            "threshold_hr": 170,
            "threshold_pace_seconds_per_km": 310,  # Decreased from 330 (faster threshold)
            "ftp_w": 280,
        },
    )
    assert r.status_code in (200, 201), f"Failed to update preferences: {r.text}"

    # Step 4: Fetch the workout again
    # With the new faster threshold pace (310 instead of 330), the same workout (avg_pace=360)
    # should have LOWER TSS because intensity factor = 310/360 = 0.861 (was 330/360 = 0.917 before)
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_v2 = r.json()

    # Step 5: Verify that TSS was refreshed, not left stale
    # Since intensity factor decreased (threshold pace got faster = harder threshold),
    # TSS should be lower
    updated_tss = workout_v2["tss"]
    assert updated_tss is not None, "TSS should still be present after threshold change"
    assert updated_tss < initial_tss, (
        f"TSS should decrease with faster pace threshold. "
        f"Initial TSS: {initial_tss}, Updated TSS: {updated_tss}, "
        f"Pace threshold changed from 330 to 310 s/km (should decrease TSS)"
    )


def test_persist_running_tss__manual_tss_not_overwritten_on_threshold_change(user_with_threshold):
    """AC: Manually-entered TSS is protected when threshold changes.

    Ensure that the fix only refreshes computed TSS; manual entries are never overwritten.
    """
    client = user_with_threshold
    # Step 1: Create a running workout with manual TSS override
    r = client.post(
        "/api/workouts",
        json={
            "workout_date": "2026-07-19",
            "name": "Test Run with Manual TSS",
            "workout_type": "run",
            "duration_seconds": 3600,
            "avg_hr": 160,
            "distance_km": 10.0,
            "tss": 95,  # Manually set TSS
        },
    )
    assert r.status_code in (200, 201), f"Failed to create workout: {r.text}"
    workout = r.json()
    workout_id = workout["id"]

    # Step 2: Verify manual TSS is stored
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_v1 = r.json()
    assert workout_v1["tss"] == 95, "Manual TSS should be preserved"

    # Step 3: Change the threshold significantly
    r = client.patch(
        "/api/user-preferences",
        json={
            "threshold_hr": 200,  # Increase threshold
            "threshold_pace_seconds_per_km": 330,
            "ftp_w": 280,
        },
    )
    assert r.status_code in (200, 201)

    # Step 4: Fetch the workout again
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_v2 = r.json()

    # Step 5: Verify manual TSS was NOT overwritten
    assert workout_v2["tss"] == 95, (
        f"Manual TSS should be protected from threshold-driven refresh. "
        f"Expected 95, got {workout_v2['tss']}"
    )


def test_persist_running_tss__computed_then_manual_then_threshold_change(user_with_threshold):
    """AC: Once a manual TSS is set, threshold changes don't override it (even if previously computed).

    Test the workflow: auto-computed → manually edited → threshold change.
    The manual value should win.
    """
    client = user_with_threshold
    # Step 1: Create workout with no manual TSS (will be computed)
    r = client.post(
        "/api/workouts",
        json={
            "workout_date": "2026-07-19",
            "name": "Test Run Workflow",
            "workout_type": "run",
            "duration_seconds": 3600,
            "avg_hr": 160,
            "distance_km": 10.0,
        },
    )
    assert r.status_code in (200, 201)
    workout = r.json()
    workout_id = workout["id"]

    # Step 2: Verify computed TSS exists
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_v1 = r.json()
    assert workout_v1["tss"] is not None

    # Step 3: Manually override the TSS
    r = client.patch(
        f"/api/workouts/{workout_id}",
        json={
            "tss": 42,  # Manual override
        },
    )
    assert r.status_code == 200

    # Step 4: Verify manual TSS is now in place
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_v2 = r.json()
    assert workout_v2["tss"] == 42

    # Step 5: Change threshold (pace, since the workout uses pace method)
    r = client.patch(
        "/api/user-preferences",
        json={
            "threshold_hr": 170,
            "threshold_pace_seconds_per_km": 310,  # Decrease threshold (faster)
            "ftp_w": 280,
        },
    )
    assert r.status_code in (200, 201)

    # Step 6: Fetch workout and verify manual TSS is still 42
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_v3 = r.json()
    assert workout_v3["tss"] == 42, (
        f"Manual TSS should remain after threshold change. Expected 42, got {workout_v3['tss']}"
    )


def test_persist_running_tss__tss_method_persisted_alongside_tss(user_with_threshold):
    """AC: The tss_method is persisted and returned alongside the TSS value.

    Verify that the computation method (power, pace, hr, etc.) is recorded and accessible.
    """
    client = user_with_threshold
    # Create a running workout where pace should be the primary method
    r = client.post(
        "/api/workouts",
        json={
            "workout_date": "2026-07-19",
            "name": "Test Run with Pace Data",
            "workout_type": "run",
            "duration_seconds": 3600,  # 1 hour
            "avg_hr": 160,
            "distance_km": 12.0,  # 12 km in 3600 s = 300 s/km average pace
            # No np (normalized power), so pace or HR should be used
        },
    )
    assert r.status_code in (200, 201), f"Failed to create workout: {r.text}"
    workout = r.json()
    workout_id = workout["id"]

    # Fetch and verify tss_method is present
    r = client.get(f"/api/workouts/{workout_id}/full")
    assert r.status_code == 200
    workout_data = r.json()
    assert "tss_method" in workout_data, "tss_method field must be present"
    assert workout_data["tss_method"] in ("power", "pace", "hr", "duration_only", "none"), (
        f"tss_method should be a valid computation method, got: {workout_data['tss_method']}"
    )
