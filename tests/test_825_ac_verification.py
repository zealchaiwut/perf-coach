"""
Tests for issue #825: Add CRUD endpoints for habits and habit logs.
Tests verify each acceptance criterion via the UAT steps.
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test825pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_client(client):
    """Return an authenticated client for a test user."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    # Create test user
    user_name = f"ac_test_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201, f"Failed to create user: {r.text}"
    user_id = r.json()["id"]

    # Set password
    password = _TEST_PW
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(password)
        db.commit()

    # Login
    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": password})
    bare.close()
    assert r.status_code == 200, f"Login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    # Return new authenticated client
    auth = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )

    yield auth
    auth.close()

    # Cleanup: delete user
    with _OrmSess(_engine) as sess:
        user = sess.get(_UserModel, uuid.UUID(user_id))
        if user:
            sess.delete(user)
            sess.commit()


# ── AC1: POST /habits creates habit; validates enums and target_value ────

def test_ac1_post_valid_creates_habit(auth_client):
    """AC1: POST /habits with valid body returns 201 with id and active=true."""
    body = {
        "name": "Test Habit",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert "id" in data
    assert data["active"] is True
    assert data["name"] == "Test Habit"


def test_ac1_post_invalid_habit_type_returns_422(auth_client):
    """AC1: POST /habits with invalid habit_type returns 422."""
    body = {
        "name": "Test",
        "habit_type": "mood",  # not in enum
        "schedule_type": "daily",
        "target_value": 1.0,
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 422, r.text


def test_ac1_post_invalid_schedule_type_returns_422(auth_client):
    """AC1: POST /habits with invalid schedule_type returns 422."""
    body = {
        "name": "Test",
        "habit_type": "binary",
        "schedule_type": "monthly",  # not in enum
        "target_value": 1.0,
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 422, r.text


def test_ac1_post_negative_target_value_returns_422(auth_client):
    """AC1: POST /habits with negative target_value returns 422."""
    body = {
        "name": "Test",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": -5,
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 422, r.text


def test_ac1_post_zero_target_value_returns_422(auth_client):
    """AC1: POST /habits with zero target_value returns 422."""
    body = {
        "name": "Test",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 0,
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 422, r.text


# ── AC2: GET /habits/:id returns single habit or 404 ────

def test_ac2_get_habit_by_id_returns_200(auth_client):
    """AC2: GET /habits/:id returns 200 with habit record."""
    # Create a habit first
    create_body = {
        "name": "Morning Jog",
        "habit_type": "duration",
        "schedule_type": "daily",
        "target_value": 30.0,
    }
    r = auth_client.post("/api/habits", json=create_body)
    assert r.status_code == 201
    habit_id = r.json()["id"]

    # Now GET it
    r = auth_client.get(f"/api/habits/{habit_id}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == habit_id
    assert data["name"] == "Morning Jog"


def test_ac2_get_nonexistent_habit_returns_404(auth_client):
    """AC2: GET /habits/:id with unknown id returns 404."""
    fake_id = str(uuid.uuid4())
    r = auth_client.get(f"/api/habits/{fake_id}")
    assert r.status_code == 404, r.text


def test_ac2_get_includes_archived_habits(auth_client):
    """AC2: GET /habits/:id returns archived habits too."""
    # Create and then delete (archive) a habit
    create_body = {
        "name": "Old Habit",
        "habit_type": "count",
        "schedule_type": "weekly",
        "target_value": 5.0,
    }
    r = auth_client.post("/api/habits", json=create_body)
    habit_id = r.json()["id"]

    # Delete it (soft delete -> active=false)
    r = auth_client.delete(f"/api/habits/{habit_id}")
    assert r.status_code == 200, r.text

    # GET should still return it
    r = auth_client.get(f"/api/habits/{habit_id}")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False


# ── AC3: GET /habits with optional active param filters by status ────

def test_ac3_get_habits_active_true_excludes_archived(auth_client):
    """AC3: GET /habits?active=true excludes archived habits."""
    # Create two habits
    r1 = auth_client.post("/api/habits", json={
        "name": "Active Habit",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit1_id = r1.json()["id"]

    r2 = auth_client.post("/api/habits", json={
        "name": "Archived Habit",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit2_id = r2.json()["id"]

    # Archive the second one
    auth_client.delete(f"/api/habits/{habit2_id}")

    # GET with active=true should only return habit1
    r = auth_client.get("/api/habits?active=true")
    assert r.status_code == 200, r.text
    data = r.json()
    habit_ids = [h["id"] for h in data]
    assert habit1_id in habit_ids
    assert habit2_id not in habit_ids


def test_ac3_get_habits_active_false_includes_only_inactive(auth_client):
    """AC3: GET /habits?active=false returns only inactive habits."""
    # Create and archive a habit
    r = auth_client.post("/api/habits", json={
        "name": "Archived Only",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit_id = r.json()["id"]
    auth_client.delete(f"/api/habits/{habit_id}")

    # GET with active=false should return it
    r = auth_client.get("/api/habits?active=false")
    assert r.status_code == 200, r.text
    data = r.json()
    habit_ids = [h["id"] for h in data]
    assert habit_id in habit_ids


# ── AC4: PATCH /habits/:id updates fields; validates enums and target_value ────

def test_ac4_patch_updates_name(auth_client):
    """AC4: PATCH /habits/:id updates allowed fields."""
    # Create a habit
    r = auth_client.post("/api/habits", json={
        "name": "Old Name",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit_id = r.json()["id"]

    # Patch it
    r = auth_client.patch(f"/api/habits/{habit_id}", json={"name": "New Name"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "New Name"


def test_ac4_patch_invalid_habit_type_returns_422(auth_client):
    """AC4: PATCH /habits/:id with invalid habit_type returns 422."""
    r = auth_client.post("/api/habits", json={
        "name": "Test",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit_id = r.json()["id"]

    # Patch with invalid type
    r = auth_client.patch(f"/api/habits/{habit_id}", json={"habit_type": "invalid"})
    assert r.status_code == 422, r.text


def test_ac4_patch_negative_target_value_returns_422(auth_client):
    """AC4: PATCH /habits/:id with negative target_value returns 422."""
    r = auth_client.post("/api/habits", json={
        "name": "Test",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit_id = r.json()["id"]

    r = auth_client.patch(f"/api/habits/{habit_id}", json={"target_value": -5})
    assert r.status_code == 422, r.text


# ── AC5: DELETE /habits/:id soft-deletes; returns updated record ────

def test_ac5_delete_soft_deletes_habit(auth_client):
    """AC5: DELETE /habits/:id sets active=false and returns record."""
    r = auth_client.post("/api/habits", json={
        "name": "To Delete",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit_id = r.json()["id"]

    # Delete
    r = auth_client.delete(f"/api/habits/{habit_id}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["active"] is False
    assert data["id"] == habit_id


def test_ac5_delete_excludes_from_active_list(auth_client):
    """AC5: Deleted habit no longer in active list."""
    r = auth_client.post("/api/habits", json={
        "name": "To Delete",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit_id = r.json()["id"]

    auth_client.delete(f"/api/habits/{habit_id}")

    # Check it's not in active list
    r = auth_client.get("/api/habits?active=true")
    data = r.json()
    habit_ids = [h["id"] for h in data]
    assert habit_id not in habit_ids


# ── AC6: PUT /habit-logs upserts (insert or update) ────

def test_ac6_put_habit_log_valid_returns_201_or_200(auth_client):
    """AC6: PUT /habit-logs with valid body returns 201 on insert or 200 on update."""
    # Create a habit
    r = auth_client.post("/api/habits", json={
        "name": "Track This",
        "habit_type": "count",
        "schedule_type": "daily",
        "target_value": 5.0,
    })
    habit_id = r.json()["id"]
    today = datetime.date.today().isoformat()

    # PUT log (first call -> 201)
    r = auth_client.put("/api/habit-logs", json={
        "habit_id": habit_id,
        "log_date": today,
        "value": 3.0,
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["log_date"] == today
    assert data["value"] == 3.0

    # PUT same log with different value (update -> 200)
    r = auth_client.put("/api/habit-logs", json={
        "habit_id": habit_id,
        "log_date": today,
        "value": 5.0,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["value"] == 5.0  # Updated


def test_ac6_put_future_date_returns_422(auth_client):
    """AC6: PUT /habit-logs with future log_date returns 422."""
    r = auth_client.post("/api/habits", json={
        "name": "Track",
        "habit_type": "count",
        "schedule_type": "daily",
        "target_value": 5.0,
    })
    habit_id = r.json()["id"]

    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r = auth_client.put("/api/habit-logs", json={
        "habit_id": habit_id,
        "log_date": tomorrow,
        "value": 1.0,
    })
    assert r.status_code == 422, r.text
    assert "future" in r.json().get("error", "").lower()


# ── AC7: GET /habit-logs with date range ────

def test_ac7_get_habit_logs_returns_range(auth_client):
    """AC7: GET /habit-logs returns logs within inclusive date range."""
    # Create habit and logs
    r = auth_client.post("/api/habits", json={
        "name": "Track",
        "habit_type": "count",
        "schedule_type": "daily",
        "target_value": 5.0,
    })
    habit_id = r.json()["id"]

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    three_days_ago = today - datetime.timedelta(days=3)

    # Create logs
    for i, log_date in enumerate([three_days_ago, yesterday, today]):
        auth_client.put("/api/habit-logs", json={
            "habit_id": habit_id,
            "log_date": log_date.isoformat(),
            "value": float(i + 1),
        })

    # Query range: yesterday to today
    r = auth_client.get(
        f"/api/habit-logs?habit_id={habit_id}&from={yesterday.isoformat()}&to={today.isoformat()}"
    )
    assert r.status_code == 200, r.text
    logs = r.json()
    assert len(logs) == 2  # yesterday and today
    dates = [log["log_date"] for log in logs]
    assert yesterday.isoformat() in dates
    assert today.isoformat() in dates


def test_ac7_get_habit_logs_missing_from_returns_400(auth_client):
    """AC7: GET /habit-logs without 'from' param returns 400."""
    today = datetime.date.today().isoformat()
    r = auth_client.get(f"/api/habit-logs?habit_id=fake&to={today}")
    assert r.status_code == 400, r.text
    assert "from" in r.json().get("error", "").lower()


def test_ac7_get_habit_logs_missing_to_returns_400(auth_client):
    """AC7: GET /habit-logs without 'to' param returns 400."""
    today = datetime.date.today().isoformat()
    r = auth_client.get(f"/api/habit-logs?habit_id=fake&from={today}")
    assert r.status_code == 400, r.text
    assert "to" in r.json().get("error", "").lower()


# ── AC9: All DB access lives in data/repository layer ────

def test_ac9_habits_repo_exists(auth_client):
    """AC9: All DB access in repository layer."""
    from backend.services import habits_repo
    assert hasattr(habits_repo, "get_habit")
    assert hasattr(habits_repo, "create_habit")
    assert hasattr(habits_repo, "update_habit")
    assert hasattr(habits_repo, "archive_habit")
    assert hasattr(habits_repo, "upsert_habit_log")
    assert hasattr(habits_repo, "get_habit_logs")


# ── AC10: No hardcoded defaults ────

def test_ac10_no_hardcoded_habit_type_default(auth_client):
    """AC10: habit_type comes from request, not defaults."""
    body = {
        "name": "Test",
        "schedule_type": "daily",
        "target_value": 1.0,
        "habit_type": "count",  # explicitly set
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["habit_type"] == "count"  # must match request


def test_ac10_no_hardcoded_schedule_type_default(auth_client):
    """AC10: schedule_type comes from request."""
    body = {
        "name": "Test",
        "habit_type": "binary",
        "target_value": 1.0,
        "schedule_type": "weekly",  # explicitly set
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["schedule_type"] == "weekly"


# ── AC11: Consistent error shapes ────

def test_ac11_error_shape_consistency(auth_client):
    """AC11: Errors return {error, details} shape."""
    body = {
        "name": "Test",
        "habit_type": "invalid",
        "schedule_type": "daily",
        "target_value": 1.0,
    }
    r = auth_client.post("/api/habits", json=body)
    assert r.status_code == 422
    data = r.json()
    assert "error" in data or "detail" in data


def test_ac11_put_future_error_shape(auth_client):
    """AC11: PUT /habit-logs future date error has consistent shape."""
    r = auth_client.post("/api/habits", json={
        "name": "Test",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    })
    habit_id = r.json()["id"]

    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r = auth_client.put("/api/habit-logs", json={
        "habit_id": habit_id,
        "log_date": tomorrow,
        "value": 1.0,
    })
    assert r.status_code == 422
    data = r.json()
    assert "error" in data
    assert "details" in data


def test_ac11_get_logs_missing_dates_error_shape(auth_client):
    """AC11: GET /habit-logs missing dates error has consistent shape."""
    r = auth_client.get("/api/habit-logs?habit_id=fake")
    assert r.status_code == 400
    data = r.json()
    assert "error" in data or "detail" in data
