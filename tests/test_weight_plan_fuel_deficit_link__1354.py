"""Tests for issue #1354: Link weight plan to fuel deficit: target rate drives deficit, mismatch surfaced (runs against UAT)"""
import os
import pytest
import httpx
from datetime import date as _date, timedelta


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
def authenticated_client(client):
    """Create a test user and return an authenticated client with session cookie."""
    # First, seed a test user
    seed_resp = client.post(
        "/api/seed/test-user",
        json={"username": "tester_1354", "password": "test_pass_1354"}
    )
    if seed_resp.status_code not in (200, 201):
        pytest.skip(f"Could not seed test user: {seed_resp.status_code}")

    # Login to get session cookie
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "tester_1354", "password": "test_pass_1354"}
    )
    if login_resp.status_code != 200:
        pytest.skip(f"Could not login: {login_resp.status_code}")

    return client


# --- Acceptance Criteria ---

def test_weight_plan_fuel_deficit_link__helper_math(authenticated_client):
    """AC: Helper `implied_deficit_kcal(target_rate_kg_per_week)` computes abs(rate) * 7700 / 7, clamped to 0-750."""
    # This helper should be in backend/services/fuel.py
    # The endpoint should return this via GET /api/fuel/settings
    # We test by creating a weight plan with a known rate and verifying the payload includes implied_deficit_kcal

    # Create a weight plan at -0.5 kg/wk
    today = _date.today()
    plan_resp = authenticated_client.post(
        "/api/weight-plans",
        json={
            "start_date": today.isoformat(),
            "start_weight_kg": 80.0,
            "goal_weight_kg": 78.0,
            "goal_date": (today + timedelta(days=14)).isoformat(),
            "target_rate_kg_per_week": -0.5,
            "phase": "cut",
        }
    )
    assert plan_resp.status_code in (200, 201), f"Failed to create plan: {plan_resp.text}"

    # Activate the plan by patching it to active=true
    plan_id = plan_resp.json().get("id")
    if plan_id:
        patch_resp = authenticated_client.patch(
            f"/api/weight-plans/{plan_id}",
            json={"active": True}
        )
        assert patch_resp.status_code in (200, 204), f"Failed to activate plan: {patch_resp.text}"

    # Get fuel settings and check implied_deficit_kcal
    settings_resp = authenticated_client.get("/api/fuel/settings")
    assert settings_resp.status_code == 200, f"Failed to get fuel settings: {settings_resp.text}"
    settings = settings_resp.json()

    # Expected: -0.5 * 7700 / 7 = -550 kcal/day → 550 abs() → clamped to max 750 → 550
    assert "implied_deficit_kcal" in settings, "implied_deficit_kcal missing from fuel settings"
    expected_implied = round(abs(-0.5) * 7700 / 7 / 10) * 10  # Nearest 10
    assert settings["implied_deficit_kcal"] == expected_implied, \
        f"Expected ~550, got {settings['implied_deficit_kcal']}"


def test_weight_plan_fuel_deficit_link__payload_fields_aligned(authenticated_client):
    """AC: Fuel settings payload includes plan_rate_kg_per_week, implied_deficit_kcal, deficit_gap_kcal, consistency."""
    today = _date.today()

    # Create a weight plan at -0.5 kg/wk and fuel settings with 500 kcal deficit (close to implied ~550)
    plan_resp = authenticated_client.post(
        "/api/weight-plans",
        json={
            "start_date": today.isoformat(),
            "start_weight_kg": 80.0,
            "goal_weight_kg": 78.0,
            "goal_date": (today + timedelta(days=14)).isoformat(),
            "target_rate_kg_per_week": -0.5,
            "phase": "cut",
        }
    )
    assert plan_resp.status_code in (200, 201)
    plan_id = plan_resp.json().get("id")

    # Activate the plan
    if plan_id:
        patch_resp = authenticated_client.patch(
            f"/api/weight-plans/{plan_id}",
            json={"active": True}
        )
        assert patch_resp.status_code in (200, 204)

    # Set fuel deficit to 500
    fuel_resp = authenticated_client.put(
        "/api/fuel/settings",
        json={"deficit_kcal": 500}
    )
    assert fuel_resp.status_code in (200, 204), f"Failed to set fuel deficit: {fuel_resp.text}"

    # Get fuel settings
    settings_resp = authenticated_client.get("/api/fuel/settings")
    assert settings_resp.status_code == 200
    settings = settings_resp.json()

    # Verify all fields present and correct
    assert "plan_rate_kg_per_week" in settings, "plan_rate_kg_per_week missing"
    assert settings["plan_rate_kg_per_week"] == -0.5, f"Expected -0.5, got {settings['plan_rate_kg_per_week']}"

    assert "implied_deficit_kcal" in settings, "implied_deficit_kcal missing"
    expected_implied = 550  # -0.5 * 7700 / 7 = -550, abs = 550
    assert settings["implied_deficit_kcal"] == expected_implied

    assert "deficit_gap_kcal" in settings, "deficit_gap_kcal missing"
    gap = settings["deficit_gap_kcal"]
    assert gap == expected_implied - 500, f"Expected gap {expected_implied - 500}, got {gap}"

    assert "consistency" in settings, "consistency missing"
    # |gap| = 50, which is <= 100, so should be 'aligned'
    assert settings["consistency"] == "aligned", f"Expected 'aligned', got {settings['consistency']}"


def test_weight_plan_fuel_deficit_link__payload_fields_mismatch(authenticated_client):
    """AC: Payload consistency is 'mismatch' when |deficit_gap_kcal| > 100."""
    today = _date.today()

    # Create a weight plan at -0.5 kg/wk (implies ~550 kcal/day)
    plan_resp = authenticated_client.post(
        "/api/weight-plans",
        json={
            "start_date": today.isoformat(),
            "start_weight_kg": 80.0,
            "goal_weight_kg": 78.0,
            "goal_date": (today + timedelta(days=14)).isoformat(),
            "target_rate_kg_per_week": -0.5,
            "phase": "cut",
        }
    )
    assert plan_resp.status_code in (200, 201)
    plan_id = plan_resp.json().get("id")

    # Activate the plan
    if plan_id:
        patch_resp = authenticated_client.patch(
            f"/api/weight-plans/{plan_id}",
            json={"active": True}
        )
        assert patch_resp.status_code in (200, 204)

    # Set fuel deficit to 300 (creates ~250 kcal gap, which is > 100)
    fuel_resp = authenticated_client.put(
        "/api/fuel/settings",
        json={"deficit_kcal": 300}
    )
    assert fuel_resp.status_code in (200, 204)

    # Get fuel settings
    settings_resp = authenticated_client.get("/api/fuel/settings")
    assert settings_resp.status_code == 200
    settings = settings_resp.json()

    assert settings["consistency"] == "mismatch", f"Expected 'mismatch', got {settings['consistency']}"


def test_weight_plan_fuel_deficit_link__payload_fields_no_plan(authenticated_client):
    """AC: Payload consistency is 'no_plan' when no active weight plan exists."""
    # Get fuel settings without an active plan
    settings_resp = authenticated_client.get("/api/fuel/settings")
    assert settings_resp.status_code == 200
    settings = settings_resp.json()

    assert "plan_rate_kg_per_week" in settings, "plan_rate_kg_per_week missing"
    assert settings["plan_rate_kg_per_week"] is None, f"Expected None, got {settings['plan_rate_kg_per_week']}"

    assert "consistency" in settings, "consistency missing"
    assert settings["consistency"] == "no_plan", f"Expected 'no_plan', got {settings['consistency']}"


def test_weight_plan_fuel_deficit_link__sync_endpoint_success(authenticated_client):
    """AC: POST /api/fuel/settings/sync-deficit sets deficit_kcal to implied value (clamped)."""
    today = _date.today()

    # Create a weight plan at -0.5 kg/wk (implies ~550 kcal/day)
    plan_resp = authenticated_client.post(
        "/api/weight-plans",
        json={
            "start_date": today.isoformat(),
            "start_weight_kg": 80.0,
            "goal_weight_kg": 78.0,
            "goal_date": (today + timedelta(days=14)).isoformat(),
            "target_rate_kg_per_week": -0.5,
            "phase": "cut",
        }
    )
    assert plan_resp.status_code in (200, 201)
    plan_id = plan_resp.json().get("id")

    # Activate the plan
    if plan_id:
        patch_resp = authenticated_client.patch(
            f"/api/weight-plans/{plan_id}",
            json={"active": True}
        )
        assert patch_resp.status_code in (200, 204)

    # Set fuel deficit to 300
    fuel_resp = authenticated_client.put(
        "/api/fuel/settings",
        json={"deficit_kcal": 300}
    )
    assert fuel_resp.status_code in (200, 204)

    # Call sync endpoint
    sync_resp = authenticated_client.post("/api/fuel/settings/sync-deficit")
    assert sync_resp.status_code == 200, f"Sync failed: {sync_resp.text}"

    # Verify deficit_kcal was updated to implied value
    settings_resp = authenticated_client.get("/api/fuel/settings")
    assert settings_resp.status_code == 200
    settings = settings_resp.json()

    expected_implied = 550
    assert settings["deficit_kcal"] == expected_implied, \
        f"Expected deficit {expected_implied}, got {settings['deficit_kcal']}"
    assert settings["consistency"] == "aligned", \
        f"Expected 'aligned' after sync, got {settings['consistency']}"


def test_weight_plan_fuel_deficit_link__sync_endpoint_no_plan(authenticated_client):
    """AC: POST /api/fuel/settings/sync-deficit returns 409 when no active weight plan."""
    # Call sync endpoint without an active plan
    sync_resp = authenticated_client.post("/api/fuel/settings/sync-deficit")
    assert sync_resp.status_code == 409, f"Expected 409, got {sync_resp.status_code}: {sync_resp.text}"


def test_weight_plan_fuel_deficit_link__sync_endpoint_clamping(authenticated_client):
    """AC: POST /api/fuel/settings/sync-deficit clamps implied deficit to 0-750 range."""
    today = _date.today()

    # Create a weight plan at -1.0 kg/wk (implies ~1100 kcal/day, should be clamped to 750)
    plan_resp = authenticated_client.post(
        "/api/weight-plans",
        json={
            "start_date": today.isoformat(),
            "start_weight_kg": 80.0,
            "goal_weight_kg": 70.0,
            "goal_date": (today + timedelta(days=70)).isoformat(),
            "target_rate_kg_per_week": -1.0,
            "phase": "cut",
        }
    )
    assert plan_resp.status_code in (200, 201)
    plan_id = plan_resp.json().get("id")

    # Activate the plan
    if plan_id:
        patch_resp = authenticated_client.patch(
            f"/api/weight-plans/{plan_id}",
            json={"active": True}
        )
        assert patch_resp.status_code in (200, 204)

    # Call sync endpoint
    sync_resp = authenticated_client.post("/api/fuel/settings/sync-deficit")
    assert sync_resp.status_code == 200

    # Verify deficit_kcal was clamped to 750
    settings_resp = authenticated_client.get("/api/fuel/settings")
    assert settings_resp.status_code == 200
    settings = settings_resp.json()

    assert settings["deficit_kcal"] == 750, \
        f"Expected clamped deficit 750, got {settings['deficit_kcal']}"
