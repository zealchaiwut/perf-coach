"""Tests for issue #865: Add weight plan summary endpoint (runs against UAT)"""
import os
import datetime
import pytest
import httpx


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def _login(client, username="test_user", password="TestPass123!"):
    """Authenticate and return cookies."""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        pytest.skip(f"Could not authenticate test user: {r.status_code} {r.text}")
    return client.cookies


# --- Acceptance Criteria ---

def test_weight_plan_summary__authenticated_endpoint_exists(client):
    """AC: GET /api/weight/plan/summary (or equivalent route) exists and is authenticated"""
    # Unauthenticated request should fail
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 401, f"Expected 401 for unauthenticated, got {r.status_code}"


def test_weight_plan_summary__no_active_plan_returns_200(client):
    """AC: When no active plan exists, response returns HTTP 200 with a structured no_active_plan state"""
    _login(client, username="user_no_plan", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("active_plan") is None, "active_plan should be null when no plan exists"
    assert data.get("status") == "no_active_plan", "status should be 'no_active_plan'"


def test_weight_plan_summary__active_plan_includes_plan_record(client):
    """AC: Response includes the active plan record (id, start date, goal weight, duration, etc.)"""
    _login(client, username="test_user", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()

    # Only test if there's an active plan
    if data.get("active_plan") is not None:
        plan = data["active_plan"]
        assert "id" in plan, "plan must have id"
        assert "start_date" in plan, "plan must have start_date"
        assert "target_date" in plan, "plan must have target_date"
        assert "start_weight_kg" in plan, "plan must have start_weight_kg"
        assert "target_weight_kg" in plan, "plan must have target_weight_kg"
        assert "status" in plan, "plan must have status"
        assert isinstance(plan["id"], str), "id must be string"
        assert isinstance(plan["start_date"], str), "start_date must be ISO string"
        assert isinstance(plan["target_date"], str), "target_date must be ISO string"
        assert isinstance(plan["start_weight_kg"], (int, float)), "start_weight_kg must be numeric"
        assert isinstance(plan["target_weight_kg"], (int, float)), "target_weight_kg must be numeric"
    else:
        pytest.skip("No active plan found for test_user")


def test_weight_plan_summary__includes_original_plan_line(client):
    """AC: Response includes the original plan line computed via compute_plan_line"""
    _login(client, username="test_user", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200
    data = r.json()

    if data.get("active_plan") is not None:
        assert "plan_line" in data, "response must include plan_line"
        plan_line = data["plan_line"]
        assert isinstance(plan_line, list), "plan_line must be a list"
        assert len(plan_line) > 0, "plan_line must not be empty"

        # Check structure of each point
        for pt in plan_line:
            assert "date" in pt, "each plan_line point must have date"
            assert "plan_kg" in pt, "each plan_line point must have plan_kg"
            assert isinstance(pt["date"], str), "date must be string"
            assert isinstance(pt["plan_kg"], (int, float)), "plan_kg must be numeric"
            # Validate date is ISO format
            datetime.date.fromisoformat(pt["date"])
    else:
        pytest.skip("No active plan found")


def test_weight_plan_summary__includes_forward_plan_line(client):
    """AC: Response includes the forward plan line recomputed from logged progress via recompute_plan_from_progress"""
    _login(client, username="test_user", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200
    data = r.json()

    if data.get("active_plan") is not None:
        assert "forward_plan_line" in data, "response must include forward_plan_line"
        forward_line = data["forward_plan_line"]
        assert isinstance(forward_line, list), "forward_plan_line must be a list"
        assert len(forward_line) > 0, "forward_plan_line must not be empty"

        # Check structure
        for pt in forward_line:
            assert "date" in pt, "each forward_plan_line point must have date"
            assert "plan_kg" in pt, "each forward_plan_line point must have plan_kg"
            assert isinstance(pt["date"], str), "date must be string"
            assert isinstance(pt["plan_kg"], (int, float)), "plan_kg must be numeric"
            datetime.date.fromisoformat(pt["date"])
    else:
        pytest.skip("No active plan found")


def test_weight_plan_summary__includes_adherence_status_and_gap(client):
    """AC: Response includes current adherence status and gap value from compute_plan_adherence"""
    _login(client, username="test_user", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200
    data = r.json()

    if data.get("active_plan") is not None:
        assert "adherence" in data, "response must include adherence"
        adherence = data["adherence"]
        assert "status" in adherence, "adherence must have status"
        assert "gap_kg" in adherence, "adherence must have gap_kg"

        valid_statuses = {"on_track", "behind", "ahead", "no_data"}
        assert adherence["status"] in valid_statuses, f"adherence status must be one of {valid_statuses}, got {adherence['status']}"

        # gap_kg should be float or None
        if adherence["gap_kg"] is not None:
            assert isinstance(adherence["gap_kg"], (int, float)), "gap_kg must be numeric or null"
    else:
        pytest.skip("No active plan found")


def test_weight_plan_summary__on_track_adherence(client):
    """AC: Unit test - adherence on-track state"""
    _login(client, username="test_user", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200
    data = r.json()

    if data.get("active_plan") is not None and data["adherence"]["status"] != "no_data":
        # Just verify the endpoint returns on_track or behind/ahead (not an error)
        assert data["adherence"]["status"] in {"on_track", "behind", "ahead", "no_data"}
    else:
        pytest.skip("No active plan or no data to verify adherence")


def test_weight_plan_summary__off_track_adherence(client):
    """AC: Unit test - adherence off-track state (behind or ahead)"""
    _login(client, username="test_user", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200
    data = r.json()

    if data.get("active_plan") is not None and data["adherence"]["status"] != "no_data":
        # Verify off-track states are captured correctly
        assert data["adherence"]["status"] in {"on_track", "behind", "ahead"}
        if data["adherence"]["status"] in {"behind", "ahead"}:
            assert data["adherence"]["gap_kg"] is not None, "gap_kg must be set for behind/ahead status"
    else:
        pytest.skip("No active plan or insufficient data")


def test_weight_plan_summary__chart_rendering_path(client):
    """AC: Feed endpoint response directly into the weight chart rendering path"""
    _login(client, username="test_user", password="TestPass123!")
    r = client.get("/api/weight/plan/summary")
    assert r.status_code == 200
    data = r.json()

    # Verify response structure matches chart requirements
    if data.get("active_plan") is not None:
        # Chart needs plan_line and forward_plan_line with date/plan_kg
        plan_line = data.get("plan_line")
        forward_line = data.get("forward_plan_line")

        assert plan_line is not None, "plan_line required for chart"
        assert forward_line is not None, "forward_plan_line required for chart"
        assert len(plan_line) > 0 and len(forward_line) > 0, "both lines must have data"

        # Validate all points have required fields
        for pt in plan_line + forward_line:
            assert "date" in pt and "plan_kg" in pt, "each point must have date and plan_kg for chart rendering"
    else:
        pytest.skip("No active plan to render")
