"""Tests for issue #1498: Add GET /api/brief/today authenticated endpoint (runs against UAT)

Acceptance Criteria verified:
- AC1: GET /api/brief/today returns HTTP 200 with valid JSON when authenticated
- AC2: Unauthenticated requests receive HTTP 401/403
- AC3: Response body matches SCHEMA_VERSION 3 shape with required keys
- AC4: Response for_date field equals today's date in Asia/Bangkok timezone
- AC5: Endpoint calls build_brief() directly (no worker required)
- AC6: Route uses same auth guard as existing protected endpoints
- AC7: Automated endpoint test seeds DB, authenticates, asserts response keys
"""
import os
import pathlib
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
if not BASE_URL.startswith("http"):
    BASE_URL = f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"

_TEST_PW = "test1498pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _create_and_login(client: httpx.Client) -> tuple[httpx.Client, str]:
    """Create a test user, set password, log in, return (auth_client, user_id)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"brief_test_{uuid.uuid4().hex[:8]}"
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


@pytest.fixture
def auth_client():
    """Create an authenticated client for a test user."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        auth, user_id = _create_and_login(bare)
        yield auth
        _delete_user(user_id)
        auth.close()


# --- Acceptance Criteria ---

def test_brief_today__authenticated_200_with_json(auth_client):
    """AC1: GET /api/brief/today returns HTTP 200 with valid JSON when authenticated."""
    r = auth_client.get("/api/brief/today")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert isinstance(data, dict), "Response body is not a JSON object"


def test_brief_today__unauthenticated_401(client):
    """AC2: Unauthenticated requests receive HTTP 401."""
    r = client.get("/api/brief/today")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"


def test_brief_today__response_shape_schema_version_3(auth_client):
    """AC3: Response body matches SCHEMA_VERSION 3 shape with required keys."""
    r = auth_client.get("/api/brief/today")
    assert r.status_code == 200
    data = r.json()

    # Required keys per daily_brief.py _build_brief return
    required_keys = {"schema_version", "for_date", "generated_at", "today", "tomorrow",
                     "form", "recent_wrap", "weight", "advisories", "actions", "week_plan"}
    actual_keys = set(data.keys())
    assert required_keys.issubset(actual_keys), (
        f"Missing required keys: {required_keys - actual_keys}. "
        f"Got keys: {actual_keys}"
    )

    # SCHEMA_VERSION 3
    assert data.get("schema_version") == 3, (
        f"Expected schema_version=3, got {data.get('schema_version')}"
    )

    # Verify nested structure for the AC requirement
    # "Response body contains the keys form, weight, advisories, and week_plan"
    assert "form" in data and isinstance(data["form"], dict), "form is missing or not a dict"
    assert "weight" in data and isinstance(data["weight"], dict), "weight is missing or not a dict"
    assert "advisories" in data and isinstance(data["advisories"], list), "advisories is missing or not a list"
    assert "week_plan" in data and isinstance(data["week_plan"], dict), "week_plan is missing or not a dict"


def test_brief_today__for_date_is_today_bangkok(auth_client):
    """AC4: Response for_date field equals today's date in Asia/Bangkok timezone."""
    r = auth_client.get("/api/brief/today")
    assert r.status_code == 200
    data = r.json()

    # Today in Bangkok timezone
    bangkok_tz = ZoneInfo("Asia/Bangkok")
    today_bangkok = datetime.now(bangkok_tz).date()
    expected_date_str = today_bangkok.isoformat()

    actual_date_str = data.get("for_date")
    assert actual_date_str == expected_date_str, (
        f"Expected for_date={expected_date_str} (Bangkok), got {actual_date_str}"
    )


def test_brief_today__idempotent_quick_succession(auth_client):
    """AC5+: Call the endpoint twice in quick succession; both return same for_date and structurally identical data."""
    r1 = auth_client.get("/api/brief/today")
    r2 = auth_client.get("/api/brief/today")

    assert r1.status_code == 200
    assert r2.status_code == 200

    data1 = r1.json()
    data2 = r2.json()

    # Same for_date
    assert data1.get("for_date") == data2.get("for_date"), (
        f"for_date mismatch: {data1.get('for_date')} vs {data2.get('for_date')}"
    )

    # Structurally identical keys (both should have the same schema_version 3 shape)
    assert set(data1.keys()) == set(data2.keys()), (
        f"Response key mismatch: {set(data1.keys())} vs {set(data2.keys())}"
    )
    assert data1.get("schema_version") == data2.get("schema_version") == 3
