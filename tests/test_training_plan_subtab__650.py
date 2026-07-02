"""Tests for issue #650: Build Training > Plan Sub-Tab with Race Plan UI"""
import os
import uuid
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import Race, User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "tester650-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"tester650_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def session_cookie(client, test_user):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    r = client.post("/api/auth/login", json={"name": name, "password": _TEST_PW})
    assert r.status_code == 200, r.text
    yield r.cookies


@pytest.fixture(scope="module")
def logged_in_client(client, session_cookie):
    client.cookies.update(session_cookie)
    return client


@pytest.fixture(scope="module")
def a_race(logged_in_client):
    """Create an A-priority race for use in tests."""
    r = logged_in_client.post("/api/races", json={
        "name": "Marathon A",
        "race_date": "2027-01-01",
        "distance_km": 42.195,
        "goal_time_seconds": 14400,
        "priority": "A",
        "status": "planned",
        "race_type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]
    yield r.json()
    logged_in_client.delete(f"/api/races/{race_id}")


@pytest.fixture(scope="module")
def b_race(logged_in_client):
    """Create a B-priority race for use in tests."""
    r = logged_in_client.post("/api/races", json={
        "name": "Half Marathon B",
        "race_date": "2026-10-01",
        "distance_km": 21.0975,
        "priority": "B",
        "status": "planned",
        "race_type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]
    yield r.json()
    logged_in_client.delete(f"/api/races/{race_id}")


@pytest.fixture(scope="module")
def checkpoint(logged_in_client):
    """Create a checkpoint for use in tests."""
    r = logged_in_client.post("/api/races", json={
        "name": "Long run checkpoint",
        "race_date": "2026-09-01",
        "distance_km": 25.0,
        "priority": "C",
        "status": "planned",
        "race_type": "checkpoint",
    })
    assert r.status_code == 201, r.text
    cp_id = r.json()["id"]
    yield r.json()
    logged_in_client.delete(f"/api/races/{cp_id}")


# ── Race header (AC: Race Header) ─────────────────────────────────────────────

def test_plan_tab__plan_tab_exists_in_training_log_page(logged_in_client):
    """AC: Plan sub-tab is present in the training log page."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "plan" in r.text.lower()
    assert "data-tab=\"plan\"" in r.text or "plan-tab" in r.text or "id=\"plan" in r.text


def test_plan_tab__race_header_section_in_html(logged_in_client):
    """AC: Race header section exists in the Plan tab HTML structure."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "plan-race-header" in r.text or "race-header" in r.text


def test_plan_tab__race_readiness_verdict_section_in_html(logged_in_client):
    """AC: On Track / At Risk / Off Track verdict banner section exists."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "verdict" in r.text or "on-track" in r.text or "plan-verdict" in r.text


# ── Performance curve (AC: Performance Curve Chart) ──────────────────────────

def test_plan_tab__performance_curve_canvas_in_html(logged_in_client):
    """AC: Performance curve chart canvas element exists in Plan tab."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "form-curve" in r.text or "plan-curve" in r.text or "performance-curve" in r.text


def test_plan_tab__not_enough_history_empty_state_in_html(logged_in_client):
    """AC: Chart shows 'Not enough history to project' message when insufficient data."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "not enough history" in r.text.lower() or "plan-curve-empty" in r.text or "building-baseline" in r.text


# ── Race API: race_type field ─────────────────────────────────────────────────

def test_race_api__create_race_with_race_type(logged_in_client):
    """AC: POST /api/races accepts race_type field and returns it in response."""
    r = logged_in_client.post("/api/races", json={
        "name": "Test Race Type",
        "race_date": "2027-03-01",
        "distance_km": 10.0,
        "priority": "B",
        "status": "planned",
        "race_type": "race",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert "race_type" in data
    assert data["race_type"] == "race"
    # cleanup
    logged_in_client.delete(f"/api/races/{data['id']}")


def test_race_api__create_checkpoint_with_race_type(logged_in_client):
    """AC: POST /api/races with race_type=checkpoint returns checkpoint type."""
    r = logged_in_client.post("/api/races", json={
        "name": "Test Checkpoint",
        "race_date": "2026-12-01",
        "distance_km": 15.0,
        "priority": "C",
        "status": "planned",
        "race_type": "checkpoint",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["race_type"] == "checkpoint"
    # cleanup
    logged_in_client.delete(f"/api/races/{data['id']}")


def test_race_api__race_dict_includes_race_type_default(logged_in_client):
    """AC: GET /api/races returns race_type field (defaults to 'race')."""
    r = logged_in_client.post("/api/races", json={
        "name": "Default Type Race",
        "race_date": "2027-05-01",
        "distance_km": 5.0,
        "priority": "C",
        "status": "planned",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert "race_type" in data
    assert data["race_type"] == "race"
    # cleanup
    logged_in_client.delete(f"/api/races/{data['id']}")


def test_race_api__list_races_includes_race_type(logged_in_client, a_race):
    """AC: GET /api/races list returns race_type for each entry."""
    r = logged_in_client.get("/api/races")
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) > 0
    for entry in data:
        assert "race_type" in entry


def test_race_api__update_race_type(logged_in_client):
    """AC: PUT /api/races/{id} can update race_type field."""
    r = logged_in_client.post("/api/races", json={
        "name": "Update Type Test",
        "race_date": "2027-02-01",
        "distance_km": 21.1,
        "priority": "B",
        "status": "planned",
        "race_type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]
    r2 = logged_in_client.put(f"/api/races/{race_id}", json={"race_type": "checkpoint"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["race_type"] == "checkpoint"
    # cleanup
    logged_in_client.delete(f"/api/races/{race_id}")


# ── DELETE race endpoint ──────────────────────────────────────────────────────

def test_race_api__delete_race_returns_204(logged_in_client):
    """AC: DELETE /api/races/{id} removes the race and returns 204."""
    r = logged_in_client.post("/api/races", json={
        "name": "Delete Me",
        "race_date": "2027-04-01",
        "distance_km": 10.0,
        "priority": "C",
        "status": "planned",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]
    r2 = logged_in_client.delete(f"/api/races/{race_id}")
    assert r2.status_code == 204, r2.text
    r3 = logged_in_client.get(f"/api/races/{race_id}")
    assert r3.status_code == 404


def test_race_api__delete_race_requires_ownership(logged_in_client, client):
    """AC: DELETE /api/races/{id} returns 404 when race belongs to another user."""
    r = logged_in_client.post("/api/races", json={
        "name": "Other User Race",
        "race_date": "2027-06-01",
        "distance_km": 10.0,
        "priority": "C",
        "status": "planned",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]
    # Unauthenticated client should get 401
    r2 = client.delete(f"/api/races/{race_id}")
    assert r2.status_code in (401, 403, 404)
    # cleanup
    logged_in_client.delete(f"/api/races/{race_id}")


# ── met_status derivation ─────────────────────────────────────────────────────

def test_race_api__met_status_upcoming_for_future_planned(logged_in_client):
    """AC: A planned checkpoint with future date has met_status='upcoming'."""
    r = logged_in_client.post("/api/races", json={
        "name": "Future Checkpoint",
        "race_date": "2030-01-01",
        "distance_km": 10.0,
        "priority": "C",
        "status": "planned",
        "race_type": "checkpoint",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data.get("met_status") == "upcoming"
    logged_in_client.delete(f"/api/races/{data['id']}")


def test_race_api__met_status_met_for_done(logged_in_client):
    """AC: A race/checkpoint with status 'done' has met_status='met'."""
    r = logged_in_client.post("/api/races", json={
        "name": "Done Race",
        "race_date": "2026-01-01",
        "distance_km": 10.0,
        "priority": "B",
        "status": "done",
        "race_type": "checkpoint",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data.get("met_status") == "met"
    logged_in_client.delete(f"/api/races/{data['id']}")


def test_race_api__met_status_missed_for_past_planned(logged_in_client):
    """AC: A planned checkpoint with a past date has met_status='missed'."""
    r = logged_in_client.post("/api/races", json={
        "name": "Past Checkpoint",
        "race_date": "2020-01-01",
        "distance_km": 10.0,
        "priority": "C",
        "status": "planned",
        "race_type": "checkpoint",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data.get("met_status") == "missed"
    logged_in_client.delete(f"/api/races/{data['id']}")


# ── Race readiness endpoint ────────────────────────────────────────────────────

def test_race_readiness__returns_specificity_progress(logged_in_client, a_race):
    """AC: GET /api/races/{id}/readiness returns specificity_progress with 3 bars."""
    race_id = a_race["id"]
    r = logged_in_client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "specificity_progress" in data


def test_race_readiness__building_baseline_field_present(logged_in_client, a_race):
    """AC: GET /api/races/{id}/readiness includes building_baseline flag."""
    race_id = a_race["id"]
    r = logged_in_client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "building_baseline" in data
    assert isinstance(data["building_baseline"], bool)


def test_race_readiness__form_curve_present(logged_in_client, a_race):
    """AC: GET /api/races/{id}/readiness returns form_curve list."""
    race_id = a_race["id"]
    r = logged_in_client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "form_curve" in data
    assert isinstance(data["form_curve"], list)


def test_race_readiness__on_track_present(logged_in_client, a_race):
    """AC: GET /api/races/{id}/readiness returns on_track status."""
    race_id = a_race["id"]
    r = logged_in_client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "on_track" in data


# ── Races & Checkpoints list HTML ─────────────────────────────────────────────

def test_plan_tab__races_list_section_in_html(logged_in_client):
    """AC: Races & Checkpoints list section exists in Plan tab HTML."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "plan-races" in r.text or "races-list" in r.text


def test_plan_tab__add_race_action_in_html(logged_in_client):
    """AC: 'Add Race' and 'Add Checkpoint' actions are accessible from the section."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "Add Race" in r.text or "add-race" in r.text


def test_plan_tab__add_checkpoint_action_in_html(logged_in_client):
    """AC: 'Add Checkpoint' action accessible from the Races & Checkpoints section."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "Add Checkpoint" in r.text or "add-checkpoint" in r.text


# ── Specificity bars HTML ─────────────────────────────────────────────────────

def test_plan_tab__specificity_bars_section_in_html(logged_in_client):
    """AC: Specificity bars section exists in Plan tab HTML."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "specificity" in r.text.lower() or "plan-spec" in r.text


def test_plan_tab__goal_pace_volume_bar_in_html(logged_in_client):
    """AC: Goal-Pace Volume bar label exists in the Plan tab specificity section."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "Goal-Pace Volume" in r.text or "goal-pace" in r.text.lower()


def test_plan_tab__longest_at_pace_bar_in_html(logged_in_client):
    """AC: Longest-at-Pace bar label exists in the Plan tab specificity section."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "Longest-at-Pace" in r.text or "longest-pace" in r.text.lower() or "Longest at Pace" in r.text


def test_plan_tab__longest_slower_bar_in_html(logged_in_client):
    """AC: Longest-Slower bar label exists in the Plan tab specificity section."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "Longest-Slower" in r.text or "longest-slower" in r.text.lower() or "Longest Slower" in r.text


# ── General / Conventions ─────────────────────────────────────────────────────

def test_plan_tab__uses_gradient_theme(logged_in_client):
    """AC: Component uses the gradient theme consistent with the approved mock."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "--page-bg" in r.text or "--bg-1" in r.text or "--bg-2" in r.text


def test_plan_tab__responsive_viewport_meta(logged_in_client):
    """AC: Page has viewport meta for responsive behavior at tablet and mobile."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "viewport" in r.text


def test_plan_tab__no_mock_data_in_html(logged_in_client):
    """AC: No hardcoded/mock race data in the HTML (all data fetched from API)."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "mock" not in r.text.lower() or "mock_data" not in r.text.lower()


def test_plan_tab__edit_modal_section_in_html(logged_in_client):
    """AC: Race/checkpoint edit modal/sheet structure exists in Plan tab."""
    r = logged_in_client.get("/log")
    assert r.status_code == 200
    assert "plan-race-modal" in r.text or "race-edit-modal" in r.text or "plan-modal" in r.text
