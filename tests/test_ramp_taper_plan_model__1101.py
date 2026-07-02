"""
Integration tests for issue #1101: Add ramp and taper parameters to plan model.

Each test is anchored to a specific acceptance criterion from the issue.
Tests run against a live UAT server (UAT_BASE_URL or http://127.0.0.1:9001).
"""
import os
import pathlib
import py_compile
import uuid

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1101pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _make_auth_client(base_client: httpx.Client) -> tuple[httpx.Client, str]:
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"plan_test_{uuid.uuid4().hex[:8]}"
    r = base_client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201, f"Failed to create user: {r.text}"
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r.status_code == 200, f"Login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    auth = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return auth, user_id


def _cleanup_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        user = sess.get(_UserModel, uuid.UUID(user_id))
        if user:
            sess.delete(user)
            sess.commit()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_client(client):
    auth, user_id = _make_auth_client(client)
    yield auth
    auth.close()
    _cleanup_user(user_id)


_FULL_RAMP_TAPER = {
    "name": "Marathon Build 2026",
    "ramp_rate": 10,
    "taper_start": 8,
    "taper_length": 2,
    "taper_shape": "linear",
}

_NO_RAMP_TAPER = {
    "name": "Base Phase",
}


# ── AC1-AC4: Model stores all four ramp/taper fields ─────────────────────────

def test_ac1_ramp_rate_stored_on_create(auth_client):
    """AC1: ramp_rate is persisted and returned on create."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["ramp_rate"] == 10


def test_ac2_taper_start_stored_on_create(auth_client):
    """AC2: taper_start is persisted and returned on create."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["taper_start"] == 8


def test_ac3_taper_length_stored_on_create(auth_client):
    """AC3: taper_length is persisted and returned on create."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["taper_length"] == 2


def test_ac4_taper_shape_stored_on_create(auth_client):
    """AC4: taper_shape is persisted and returned on create."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["taper_shape"] == "linear"


# ── AC5: All fields nullable/optional ─────────────────────────────────────────

def test_ac5_all_ramp_taper_fields_nullable(auth_client):
    """AC5: Plan can be created without any ramp/taper fields."""
    r = auth_client.post("/api/plans", json=_NO_RAMP_TAPER)
    assert r.status_code == 201, r.text


# ── AC6: Fields exposed via create/read/update ────────────────────────────────

def test_ac6_create_returns_all_ramp_taper_keys(auth_client):
    """AC6: POST response includes all four ramp/taper fields as keys."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    assert r.status_code == 201, r.text
    data = r.json()
    for field in ("ramp_rate", "taper_start", "taper_length", "taper_shape"):
        assert field in data, f"Missing field: {field}"


def test_ac6_get_returns_all_ramp_taper_keys(auth_client):
    """AC6: GET /api/plans/{id} response includes all four ramp/taper fields."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    plan_id = r.json()["id"]
    r2 = auth_client.get(f"/api/plans/{plan_id}")
    assert r2.status_code == 200, r2.text
    data = r2.json()
    for field in ("ramp_rate", "taper_start", "taper_length", "taper_shape"):
        assert field in data, f"Missing field on GET: {field}"


def test_ac6_patch_updates_taper_shape(auth_client):
    """AC6 (update): PATCH /api/plans/{id} updates taper_shape and returns 200."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    plan_id = r.json()["id"]
    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"taper_shape": "step"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["taper_shape"] == "step"


def test_ac6_patch_leaves_other_ramp_fields_unchanged(auth_client):
    """AC6 (update): PATCH only changing taper_shape leaves other ramp/taper fields unchanged."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    plan_id = r.json()["id"]
    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"taper_shape": "step"})
    data = r2.json()
    assert data["ramp_rate"] == 10
    assert data["taper_start"] == 8
    assert data["taper_length"] == 2


# ── AC7: Round-trip — values unchanged on read ────────────────────────────────

def test_ac7_ramp_taper_values_roundtrip_on_get(auth_client):
    """AC7: Plan created with ramp/taper values returns those values unchanged on GET."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]
    r2 = auth_client.get(f"/api/plans/{plan_id}")
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["ramp_rate"] == 10
    assert data["taper_start"] == 8
    assert data["taper_length"] == 2
    assert data["taper_shape"] == "linear"


# ── AC8: Plan without ramp/taper returns null ─────────────────────────────────

def test_ac8_null_when_no_ramp_taper_on_create(auth_client):
    """AC8: Plan created without ramp/taper fields returns null for those fields on create."""
    r = auth_client.post("/api/plans", json=_NO_RAMP_TAPER)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["ramp_rate"] is None
    assert data["taper_start"] is None
    assert data["taper_length"] is None
    assert data["taper_shape"] is None


def test_ac8_null_when_no_ramp_taper_on_get(auth_client):
    """AC8: Plan created without ramp/taper returns null for those fields on GET."""
    r = auth_client.post("/api/plans", json=_NO_RAMP_TAPER)
    plan_id = r.json()["id"]
    r2 = auth_client.get(f"/api/plans/{plan_id}")
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["ramp_rate"] is None
    assert data["taper_start"] is None
    assert data["taper_length"] is None
    assert data["taper_shape"] is None


# ── AC5 / UAT Step 5: Invalid taper_shape is rejected ─────────────────────────

def test_ac5_invalid_taper_shape_rejected_on_create(auth_client):
    """AC5 / UAT Step 5: taper_shape='zigzag' returns 400 or 422."""
    r = auth_client.post("/api/plans", json={**_FULL_RAMP_TAPER, "taper_shape": "zigzag"})
    assert r.status_code in (400, 422), f"Expected 400/422, got {r.status_code}: {r.text}"


def test_ac5_invalid_taper_shape_rejected_on_patch(auth_client):
    """AC5: PATCH with taper_shape='zigzag' returns 400 or 422."""
    r = auth_client.post("/api/plans", json=_FULL_RAMP_TAPER)
    plan_id = r.json()["id"]
    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"taper_shape": "zigzag"})
    assert r2.status_code in (400, 422), f"Expected 400/422, got {r2.status_code}: {r2.text}"


def test_ac5_valid_taper_shapes_accepted(auth_client):
    """AC5: All three valid taper_shape values are accepted."""
    for shape in ("linear", "step", "exponential"):
        r = auth_client.post("/api/plans", json={**_FULL_RAMP_TAPER, "taper_shape": shape})
        assert r.status_code == 201, f"Expected 201 for shape={shape!r}: {r.text}"
        assert r.json()["taper_shape"] == shape


# ── AC9: py_compile passes on modified Python files ───────────────────────────

def test_ac9_py_compile_models():
    """AC9: backend/models.py compiles without errors."""
    py_compile.compile(str(_root / "backend" / "models.py"), doraise=True)


def test_ac9_py_compile_main():
    """AC9: backend/main.py compiles without errors."""
    py_compile.compile(str(_root / "backend" / "main.py"), doraise=True)


# ── UAT Step 1: Full POST with all ramp/taper fields ─────────────────────────

def test_uat_step1_create_plan_with_all_fields(auth_client):
    """UAT Step 1: POST with all four ramp/taper fields returns 201 with correct values."""
    r = auth_client.post("/api/plans", json={
        "name": "UAT Plan",
        "ramp_rate": 10,
        "taper_start": 8,
        "taper_length": 2,
        "taper_shape": "linear",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["ramp_rate"] == 10
    assert data["taper_start"] == 8
    assert data["taper_length"] == 2
    assert data["taper_shape"] == "linear"


# ── UAT Step 3: PATCH taper_shape only ───────────────────────────────────────

def test_uat_step3_patch_taper_shape_to_step(auth_client):
    """UAT Step 3: PATCH changes taper_shape to 'step'; other ramp fields unchanged."""
    r = auth_client.post("/api/plans", json={
        "name": "UAT Plan Step 3",
        "ramp_rate": 10,
        "taper_start": 8,
        "taper_length": 2,
        "taper_shape": "linear",
    })
    plan_id = r.json()["id"]
    r2 = auth_client.patch(f"/api/plans/{plan_id}", json={"taper_shape": "step"})
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["taper_shape"] == "step"
    assert data["ramp_rate"] == 10
    assert data["taper_start"] == 8
    assert data["taper_length"] == 2
