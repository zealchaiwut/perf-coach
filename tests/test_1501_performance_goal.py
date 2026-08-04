"""Tests for issue #1501: PerformanceGoal model and goal setup flow.

AC coverage:
- AC1: PerformanceGoal model exists with correct fields
- AC2: Migration — table is reachable via API
- AC3: Only one active goal per user at a time (application-layer enforcement)
- AC4: GET /api/coach/goal returns active goal or null; requires auth
- AC5/AC6: PUT /api/coach/goal creates/replaces goal; valid half-marathon returns 200
- AC7: Invalid payloads return 422 (bad enum, negative time, past date)
- AC13 (unit): GET null, GET active, PUT creates, PUT replaces (old flipped inactive), PUT rejects each invalid
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import PerformanceGoal, User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1501pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    try:
        from dotenv import dotenv_values
        _env = dotenv_values(_env_file)
        _uat_url = _env.get("DATABASE_URL_UAT")
    except ImportError:
        _uat_url = os.environ.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _create_and_login(client: httpx.Client) -> tuple:
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"goal_test_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r.status_code == 200, f"login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    auth = httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return auth, user_id


def _delete_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: Model structure ───────────────────────────────────────────────────────

def test_ac1_model_importable_and_correct_tablename():
    """AC1: PerformanceGoal model importable, maps to performance_goals."""
    assert PerformanceGoal.__tablename__ == "performance_goals"


def test_ac1_required_columns_present():
    """AC1: performance_goals has all required columns."""
    col_names = {c.name for c in PerformanceGoal.__table__.columns}
    required = {"id", "user_id", "race_distance", "target_time", "race_date", "created_at", "active"}
    assert required <= col_names, f"Missing columns: {required - col_names}"


def test_ac1_race_distance_check_constraint_exists():
    """AC1: CheckConstraint exists on race_distance to enforce enum values."""
    constraint_names = {c.name for c in PerformanceGoal.__table__.constraints}
    assert "ck_performance_goals_race_distance_values" in constraint_names


# ── AC4: GET /api/coach/goal requires auth ─────────────────────────────────────

def test_ac4_get_goal_unauthenticated_returns_401(client):
    """AC4: GET /api/coach/goal returns 401 when not logged in."""
    r = client.get("/api/coach/goal")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def test_ac4_get_goal_returns_null_when_no_goal(client):
    """AC4 / AC13: GET /api/coach/goal returns null when user has no active goal."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/coach/goal")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["goal"] is None, f"Expected null goal, got {data['goal']}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac4_get_goal_returns_active_goal(client):
    """AC4 / AC13: GET /api/coach/goal returns the active goal object."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        # Create a goal first
        future = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
        put_r = auth.put("/api/coach/goal", json={
            "race_distance": "half",
            "target_time": 6300,
            "race_date": future,
        })
        assert put_r.status_code == 200, put_r.text

        r = auth.get("/api/coach/goal")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["goal"] is not None
        assert data["goal"]["race_distance"] == "half"
        assert data["goal"]["target_time"] == 6300
        assert data["goal"]["active"] is True
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC5/AC6: PUT /api/coach/goal ──────────────────────────────────────────────

def test_ac5_put_goal_unauthenticated_returns_401(client):
    """AC5: PUT /api/coach/goal returns 401 when not logged in."""
    future = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
    r = client.put("/api/coach/goal", json={
        "race_distance": "half",
        "target_time": 6300,
        "race_date": future,
    })
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def test_ac6_put_half_marathon_returns_200(client):
    """AC6: PUT with half/6300/future date returns 200 with saved goal."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = "2026-12-06"
        r = auth.put("/api/coach/goal", json={
            "race_distance": "half",
            "target_time": 6300,
            "race_date": future,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "goal" in data, f"PUT must return {{\"goal\": ...}} envelope, got: {list(data.keys())}"
        goal = data["goal"]
        assert goal["race_distance"] == "half"
        assert goal["target_time"] == 6300
        assert goal["race_date"] == future
        assert goal["active"] is True
        assert "id" in goal
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac13_put_creates_goal(client):
    """AC13: PUT creates a new goal row when none exists."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "5k",
            "target_time": 1200,
            "race_date": future,
        })
        assert r.status_code == 200, r.text

        with _OrmSess(_engine) as db:
            count = db.execute(
                text("SELECT COUNT(*) FROM performance_goals WHERE user_id = :uid"),
                {"uid": user_id},
            ).scalar()
        assert count == 1
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_ac13_put_replaces_prior_active_goal(client):
    """AC3 / AC13: Second PUT flips old goal to active=false; only one active at a time."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future1 = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        r1 = auth.put("/api/coach/goal", json={
            "race_distance": "5k",
            "target_time": 1200,
            "race_date": future1,
        })
        assert r1.status_code == 200, r1.text
        old_id = r1.json()["goal"]["id"]

        future2 = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
        r2 = auth.put("/api/coach/goal", json={
            "race_distance": "marathon",
            "target_time": 14400,
            "race_date": future2,
        })
        assert r2.status_code == 200, r2.text
        new_id = r2.json()["goal"]["id"]
        assert new_id != old_id

        # Old goal should be inactive
        with _OrmSess(_engine) as db:
            old_active = db.execute(
                text("SELECT active FROM performance_goals WHERE id = :id"),
                {"id": old_id},
            ).scalar()
            active_count = db.execute(
                text("SELECT COUNT(*) FROM performance_goals WHERE user_id = :uid AND active = true"),
                {"uid": user_id},
            ).scalar()

        assert old_active is False, "Prior goal should have active=false after replacement"
        assert active_count == 1, f"Only one active goal should exist, found {active_count}"

        # GET should return the new goal
        r = auth.get("/api/coach/goal")
        assert r.status_code == 200
        assert r.json()["goal"]["id"] == new_id
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC7: Invalid payloads return 422 ──────────────────────────────────────────

def test_ac7_put_invalid_enum_returns_422(client):
    """AC7 / AC13: PUT with invalid race_distance returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "ultra",
            "target_time": 6300,
            "race_date": future,
        })
        assert r.status_code == 422, f"Expected 422 for bad enum, got {r.status_code}: {r.text}"
        data = r.json()
        assert "detail" in data
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac7_put_negative_time_returns_422(client):
    """AC7 / AC13: PUT with negative target_time returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "5k",
            "target_time": -100,
            "race_date": future,
        })
        assert r.status_code == 422, f"Expected 422 for negative time, got {r.status_code}: {r.text}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac7_put_zero_time_returns_422(client):
    """AC7 / AC13: PUT with target_time=0 returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "5k",
            "target_time": 0,
            "race_date": future,
        })
        assert r.status_code == 422, f"Expected 422 for zero time, got {r.status_code}: {r.text}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac7_put_past_date_returns_422(client):
    """AC7 / AC13: PUT with past race_date returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "5k",
            "target_time": 1200,
            "race_date": yesterday,
        })
        assert r.status_code == 422, f"Expected 422 for past date, got {r.status_code}: {r.text}"
        data = r.json()
        assert "detail" in data
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac7_put_today_date_returns_422(client):
    """AC7: PUT with today's date (not future) returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "5k",
            "target_time": 1200,
            "race_date": today,
        })
        assert r.status_code == 422, f"Expected 422 for today date, got {r.status_code}: {r.text}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac7_put_invalid_date_format_returns_422(client):
    """AC7: PUT with non-ISO race_date returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.put("/api/coach/goal", json={
            "race_distance": "5k",
            "target_time": 1200,
            "race_date": "not-a-date",
        })
        assert r.status_code == 422, f"Expected 422 for bad date format, got {r.status_code}: {r.text}"
    finally:
        auth.close()
        _delete_user(user_id)
