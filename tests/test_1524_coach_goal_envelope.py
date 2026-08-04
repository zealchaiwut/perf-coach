"""Tests for issue #1524: GET and PUT /api/coach/goal must return consistent {goal: ...} envelopes.

AC coverage:
- PUT /api/coach/goal must return {"goal": {...}} matching GET's envelope
- GET /api/coach/goal envelope structure is unchanged
- Both verbs return the same top-level key "goal"
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
_TEST_PW = "test1524pw!"

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

    user_name = f"env_test_{uuid.uuid4().hex[:8]}"
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


def test_put_returns_goal_envelope(client):
    """PUT /api/coach/goal must return {\"goal\": {...}} not a bare dict."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "10k",
            "target_time": 2700,
            "race_date": future,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "goal" in data, (
            f"PUT /api/coach/goal must return {{\"goal\": {{...}}}}, got top-level keys: {list(data.keys())}"
        )
        goal = data["goal"]
        assert goal["race_distance"] == "10k"
        assert goal["target_time"] == 2700
        assert goal["race_date"] == future
        assert goal["active"] is True
        assert "id" in goal
    finally:
        auth.close()
        _delete_user(user_id)


def test_put_and_get_return_same_envelope_shape(client):
    """PUT and GET /api/coach/goal must both use the {\"goal\": ...} envelope."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = (datetime.date.today() + datetime.timedelta(days=120)).isoformat()
        r_put = auth.put("/api/coach/goal", json={
            "race_distance": "half",
            "target_time": 6300,
            "race_date": future,
        })
        assert r_put.status_code == 200, r_put.text
        put_data = r_put.json()

        r_get = auth.get("/api/coach/goal")
        assert r_get.status_code == 200, r_get.text
        get_data = r_get.json()

        # Both must have a top-level "goal" key
        assert "goal" in put_data, (
            f"PUT envelope missing 'goal' key; got {list(put_data.keys())}"
        )
        assert "goal" in get_data, (
            f"GET envelope missing 'goal' key; got {list(get_data.keys())}"
        )

        # The goal objects returned by PUT and GET must agree on key fields
        put_goal = put_data["goal"]
        get_goal = get_data["goal"]
        assert put_goal["id"] == get_goal["id"]
        assert put_goal["race_distance"] == get_goal["race_distance"]
        assert put_goal["target_time"] == get_goal["target_time"]
        assert put_goal["race_date"] == get_goal["race_date"]
        assert put_goal["active"] == get_goal["active"]
    finally:
        auth.close()
        _delete_user(user_id)


def test_put_goal_has_no_bare_top_level_race_distance(client):
    """PUT response must NOT expose race_distance at the top level (old bare-dict shape)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        future = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
        r = auth.put("/api/coach/goal", json={
            "race_distance": "marathon",
            "target_time": 14400,
            "race_date": future,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "race_distance" not in data, (
            "PUT must not return race_distance at the top level; "
            "it must be nested under data[\"goal\"]"
        )
    finally:
        auth.close()
        _delete_user(user_id)
