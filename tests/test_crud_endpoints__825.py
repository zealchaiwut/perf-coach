"""Tests for issue #825: Add CRUD endpoints for habits and habit logs (runs against UAT)"""
import os
import pathlib
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "test825pw"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


@pytest.fixture(scope="session", autouse=True)
def _wait_for_server():
    """Block until the UAT server is ready (max 30 s).

    deploy-start.sh backgrounds startup and returns after 1 s; uvicorn may
    need a few extra seconds before it accepts connections.
    """
    import time
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            httpx.get(f"{BASE_URL}/api/auth/me", timeout=2.0)
            return
        except (httpx.ConnectError, httpx.ConnectTimeout):
            time.sleep(1)
    raise RuntimeError(f"Server at {BASE_URL} not ready after 30 s")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    """Create and cleanup a test user."""
    name = f"tester825_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture(scope="module")
def authenticated_client(user_id):
    """Authenticated httpx.Client with session + CSRF pre-configured."""
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    # Use a temporary bare client so the shared client stays cookie-free
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        res = bare.post("/api/auth/login",
                        json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session_cookie = res.cookies.get("session")
    csrf_token = res.cookies.get(CSRF_COOKIE_NAME)
    c = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield c
    c.close()


# --- Acceptance Criteria Tests ---

def test_crud_endpoints__post_habits_valid(authenticated_client):
    # AC: POST /habits creates a new habit with valid enum and positive target_value
    r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Morning Run",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily",
            "target_value": 5.0
        }
    )
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["id"]
    assert data["name"] == "Morning Run"
    assert data["habit_type"] == "binary"
    assert data["schedule_type"] == "daily"
    assert float(data["target_value"]) == 5.0
    assert data["active"] is True


def test_crud_endpoints__post_habits_invalid_habit_type(authenticated_client):
    # AC: POST /habits returns 422 if habit_type is outside enum
    r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Invalid Habit",
            "tracking_type": "daily_checkmark",
            "habit_type": "invalid_type",
            "schedule_type": "daily"
        }
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    assert "habit_type" in r.text or "must be one of" in r.text


def test_crud_endpoints__post_habits_invalid_schedule_type(authenticated_client):
    # AC: POST /habits returns 422 if schedule_type is outside enum
    r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Invalid Habit",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "invalid_schedule"
        }
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    assert "schedule_type" in r.text or "must be one of" in r.text


def test_crud_endpoints__post_habits_negative_target_value(authenticated_client):
    # AC: POST /habits returns 422 if target_value is present but not positive
    r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Bad Target",
            "tracking_type": "daily_checkmark",
            "habit_type": "count",
            "schedule_type": "daily",
            "target_value": -5.0
        }
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    assert "positive" in r.text or "target_value" in r.text


def test_crud_endpoints__get_habits_by_id(authenticated_client):
    # AC: GET /habits/:id returns a single habit record or 404 if not found
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Test Habit",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    get_r = authenticated_client.get(f"/api/habits/{habit_id}")
    assert get_r.status_code == 200, f"Expected 200, got {get_r.status_code}: {get_r.text}"
    data = get_r.json()
    assert data["id"] == habit_id
    assert data["name"] == "Test Habit"


def test_crud_endpoints__get_habits_by_id_not_found(authenticated_client):
    # AC: GET /habits/:id returns 404 if not found
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = authenticated_client.get(f"/api/habits/{fake_id}")
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


def test_crud_endpoints__get_habits_list(authenticated_client):
    # AC: GET /habits returns a list of habits with optional active filtering
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Active Habit",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"

    list_r = authenticated_client.get("/api/habits")
    assert list_r.status_code == 200, f"Expected 200, got {list_r.status_code}: {list_r.text}"
    habits = list_r.json()
    assert isinstance(habits, list)
    assert any(h["name"] == "Active Habit" for h in habits)


def test_crud_endpoints__get_habits_filtered_by_active(authenticated_client):
    # AC: GET /habits with active=true filters archived habits
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Will Be Archived",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    delete_r = authenticated_client.delete(f"/api/habits/{habit_id}")
    assert delete_r.status_code == 200, f"Delete failed: {delete_r.text}"

    active_r = authenticated_client.get("/api/habits?active=true")
    assert active_r.status_code == 200, f"Expected 200, got {active_r.status_code}: {active_r.text}"
    active_habits = active_r.json()
    assert not any(h["id"] == habit_id for h in active_habits)


def test_crud_endpoints__patch_habits_update_name(authenticated_client):
    # AC: PATCH /habits/:id updates allowed fields on existing habit
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Original Name",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    patch_r = authenticated_client.patch(
        f"/api/habits/{habit_id}",
        json={"name": "Updated Name"}
    )
    assert patch_r.status_code == 200, f"Expected 200, got {patch_r.status_code}: {patch_r.text}"
    data = patch_r.json()
    assert data["name"] == "Updated Name"
    assert data["id"] == habit_id


def test_crud_endpoints__patch_habits_invalid_enum(authenticated_client):
    # AC: PATCH /habits/:id applies same enum validations as create
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Test",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    patch_r = authenticated_client.patch(
        f"/api/habits/{habit_id}",
        json={"schedule_type": "invalid"}
    )
    assert patch_r.status_code == 422, f"Expected 422, got {patch_r.status_code}: {patch_r.text}"


def test_crud_endpoints__delete_habits_soft_delete(authenticated_client):
    # AC: DELETE /habits/:id sets active=false and returns updated record
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "To Delete",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    delete_r = authenticated_client.delete(f"/api/habits/{habit_id}")
    assert delete_r.status_code == 200, f"Expected 200, got {delete_r.status_code}: {delete_r.text}"
    data = delete_r.json()
    assert data["id"] == habit_id
    assert data["active"] is False


def test_crud_endpoints__put_habit_logs_upsert_create(authenticated_client):
    # AC: PUT /habit-logs upserts log for (habit_id, log_date) pair
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Log Test",
            "tracking_type": "daily_checkmark",
            "habit_type": "count",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    today = datetime.now(timezone.utc).date().isoformat()

    log_r = authenticated_client.put(
        "/api/habit-logs",
        json={
            "habit_id": habit_id,
            "log_date": today,
            "value": 5.0
        }
    )
    assert log_r.status_code in [
        200, 201], f"Expected 200/201, got {log_r.status_code}: {log_r.text}"
    log_data = log_r.json()
    assert log_data["habit_id"] == habit_id
    assert log_data["log_date"] == today
    assert float(log_data["value"]) == 5.0


def test_crud_endpoints__put_habit_logs_upsert_update(authenticated_client):
    # AC: PUT /habit-logs subsequent calls update, no duplicates created
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Log Upsert Test",
            "tracking_type": "daily_checkmark",
            "habit_type": "count",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    today = datetime.now(timezone.utc).date().isoformat()

    log_r1 = authenticated_client.put(
        "/api/habit-logs",
        json={
            "habit_id": habit_id,
            "log_date": today,
            "value": 3.0
        }
    )
    assert log_r1.status_code in [
        200, 201], f"First upsert failed: {log_r1.text}"

    log_r2 = authenticated_client.put(
        "/api/habit-logs",
        json={
            "habit_id": habit_id,
            "log_date": today,
            "value": 7.0
        }
    )
    assert log_r2.status_code == 200, f"Expected 200, got {log_r2.status_code}: {log_r2.text}"
    log_data = log_r2.json()
    assert float(log_data["value"]) == 7.0


def test_crud_endpoints__put_habit_logs_future_date_rejected(authenticated_client):
    # AC: PUT /habit-logs returns 422 if log_date is in the future
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Future Test",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    tomorrow = (datetime.now(timezone.utc).date() + \
                timedelta(days=1)).isoformat()

    log_r = authenticated_client.put(
        "/api/habit-logs",
        json={
            "habit_id": habit_id,
            "log_date": tomorrow,
            "value": 1.0
        }
    )
    assert log_r.status_code == 422, f"Expected 422, got {log_r.status_code}: {log_r.text}"
    assert "future" in log_r.text or "log_date" in log_r.text


def test_crud_endpoints__get_habit_logs_range(authenticated_client):
    # AC: GET /habit-logs returns logs in inclusive date range
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Range Test",
            "tracking_type": "daily_checkmark",
            "habit_type": "count",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    today_str = today.isoformat()

    log_r1 = authenticated_client.put(
        "/api/habit-logs",
        json={
            "habit_id": habit_id,
            "log_date": yesterday,
            "value": 2.0
        }
    )
    assert log_r1.status_code in [200, 201], f"First log failed: {log_r1.text}"

    log_r2 = authenticated_client.put(
        "/api/habit-logs",
        json={
            "habit_id": habit_id,
            "log_date": today_str,
            "value": 3.0
        }
    )
    assert log_r2.status_code in [
        200, 201], f"Second log failed: {log_r2.text}"

    from_date = (today - timedelta(days=2)).isoformat()
    to_date = today_str
    get_r = authenticated_client.get(
        f"/api/habit-logs?habit_id={habit_id}&from={from_date}&to={to_date}"
    )
    assert get_r.status_code == 200, f"Expected 200, got {get_r.status_code}: {get_r.text}"
    logs = get_r.json()
    assert isinstance(logs, list)
    assert len(logs) == 2


def test_crud_endpoints__get_habit_logs_missing_from_param(authenticated_client):
    # AC: GET /habit-logs returns 400 if from param is missing
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Param Test",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    get_r = authenticated_client.get(
        f"/api/habit-logs?habit_id={habit_id}&to=2026-06-20"
    )
    assert get_r.status_code == 400, f"Expected 400, got {get_r.status_code}: {get_r.text}"
    assert "from" in get_r.text or "required" in get_r.text


def test_crud_endpoints__get_habit_logs_missing_to_param(authenticated_client):
    # AC: GET /habit-logs returns 400 if to param is missing
    create_r = authenticated_client.post(
        "/api/habits",
        json={
            "name": "Param Test 2",
            "tracking_type": "daily_checkmark",
            "habit_type": "binary",
            "schedule_type": "daily"
        }
    )
    assert create_r.status_code == 201, f"Create failed: {create_r.text}"
    habit_id = create_r.json()["id"]

    get_r = authenticated_client.get(
        f"/api/habit-logs?habit_id={habit_id}&from=2026-06-01"
    )
    assert get_r.status_code == 400, f"Expected 400, got {get_r.status_code}: {get_r.text}"
    assert "to" in get_r.text or "required" in get_r.text
