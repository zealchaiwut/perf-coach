"""Tests for issue #1138: plan router routes missing /api/ prefix.

Acceptance criteria verified:
- AC1: APIRouter in backend/routers/projection.py is configured with prefix="/api"
       so race/checkpoint/projection routes are served under /api/plans/{plan_id}/...
- AC2: Un-prefixed paths (e.g. GET /plans/{plan_id}/races) return 404;
       /api/plans/{plan_id}/races returns the correct response
- AC3: _planRaceUrl helper in training-projection.js prepends /api
- AC4: All race/checkpoint/projection endpoints return the same data as before —
       only the URL prefix changes
- AC5: No duplicate route registrations (old un-prefixed paths not active alongside new ones)
"""
from __future__ import annotations

import os
import pathlib
import re
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "planprefix1138!"

try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

if _uat_url:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw
    from backend.models import User as _UserModel
    _engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _engine = None


def _skip_if_no_db():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


# ── AC1: router prefix check (static / no server needed) ─────────────────────

def test_ac1_router_has_api_prefix():
    """AC1: The APIRouter in projection.py must have prefix='/api'."""
    from backend.routers.projection import router
    assert router.prefix == "/api", (
        f"Expected router.prefix='/api', got {router.prefix!r}. "
        "Add prefix='/api' to APIRouter() in backend/routers/projection.py."
    )


def test_ac1_routes_start_with_api_plans():
    """AC1: Every route path in the router starts with /api/plans/."""
    from backend.routers.projection import router
    for route in router.routes:
        path = getattr(route, "path", "")
        assert path.startswith("/api/plans/"), (
            f"Route {path!r} does not start with '/api/plans/'. "
            "All plan-router routes must be prefixed /api."
        )


# ── AC3: frontend _planRaceUrl prepends /api ──────────────────────────────────

def test_ac3_plan_race_url_helper_has_api_prefix():
    """AC3: _planRaceUrl in training-projection.js must return a path starting with /api/plans/."""
    js_path = _ROOT / "frontend" / "js" / "training-projection.js"
    assert js_path.exists(), f"training-projection.js not found at {js_path}"
    content = js_path.read_text()
    # Find the _planRaceUrl function body
    m = re.search(r'function _planRaceUrl\([^)]*\)\s*\{([^}]+)\}', content)
    assert m, "_planRaceUrl function not found in training-projection.js"
    body = m.group(1)
    assert "/api/plans/" in body, (
        f"_planRaceUrl must use '/api/plans/' but got: {body.strip()!r}"
    )


def test_ac3_training_performance_projection_fetch_has_api_prefix():
    """AC3: training-performance.js projection fetch must target /api/plans/."""
    js_path = _ROOT / "frontend" / "js" / "training-performance.js"
    assert js_path.exists(), f"training-performance.js not found at {js_path}"
    content = js_path.read_text()
    # Should not have the old un-prefixed /plans/ fetch for projection
    old_pattern = re.search(r"fetch\(['\"]\/plans\/", content)
    assert not old_pattern, (
        "training-performance.js still fetches from '/plans/' (un-prefixed). "
        "Update to '/api/plans/'."
    )


# ── AC5: no duplicate routes (static check) ──────────────────────────────────

def test_ac5_no_duplicate_route_registrations():
    """AC5: The app must not register both /plans/... and /api/plans/... for the same resource."""
    from backend.main import app
    paths = [getattr(r, "path", "") for r in app.routes]
    unprefixed = [p for p in paths if re.match(r"^/plans/", p)]
    assert not unprefixed, (
        f"Found un-prefixed plan routes still registered: {unprefixed}. "
        "Only /api/plans/... routes should exist."
    )


# ── Integration tests (require live UAT server) ───────────────────────────────

@pytest.fixture(scope="module")
def authed_client():
    """Create a test user, authenticate, yield client + user_id. Cleanup after."""
    _skip_if_no_db()
    uname = f"prefix1138_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname}, cookies=_admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get("csrf-token")

    client = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, "csrf-token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield client, user_id

    client.close()
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


def test_ac2_unprefixed_races_returns_404(authed_client):
    """AC2: GET /plans/{plan_id}/races (un-prefixed) returns 404."""
    client, user_id = authed_client
    r = client.get(f"/plans/{user_id}/races")
    assert r.status_code == 404, (
        f"Expected 404 for un-prefixed /plans/{{id}}/races, got {r.status_code}. "
        "The old path must no longer be served."
    )


def test_ac2_prefixed_races_returns_200(authed_client):
    """AC2: GET /api/plans/{plan_id}/races returns 200."""
    client, user_id = authed_client
    r = client.get(f"/api/plans/{user_id}/races")
    assert r.status_code == 200, (
        f"Expected 200 for /api/plans/{{id}}/races, got {r.status_code}: {r.text}"
    )
    assert isinstance(r.json(), list), "Response must be a list"


def test_ac4_race_crud_works_at_api_prefix(authed_client):
    """AC4: Full race CRUD round-trip works at /api/plans/ prefix — same data, new URL."""
    client, user_id = authed_client

    # Create
    r = client.post(f"/api/plans/{user_id}/races", json={
        "date": "2027-09-01",
        "distance": 42.195,
        "type": "race",
        "name": "Test Marathon 1138",
    })
    assert r.status_code == 201, f"create failed: {r.text}"
    data = r.json()
    race_id = data["id"]
    assert data["name"] == "Test Marathon 1138"
    assert data["distance"] == pytest.approx(42.195, rel=1e-3)

    # Read list
    r2 = client.get(f"/api/plans/{user_id}/races")
    assert r2.status_code == 200
    ids = [row["id"] for row in r2.json()]
    assert race_id in ids

    # Patch
    r3 = client.patch(f"/api/plans/{user_id}/races/{race_id}", json={"name": "Updated 1138"})
    assert r3.status_code == 200, f"patch failed: {r3.text}"
    assert r3.json()["name"] == "Updated 1138"

    # Delete
    r4 = client.delete(f"/api/plans/{user_id}/races/{race_id}")
    assert r4.status_code == 204, f"delete failed: {r4.text}"

    # Confirm gone
    r5 = client.get(f"/api/plans/{user_id}/races/{race_id}")
    assert r5.status_code == 404


def test_ac2_unprefixed_projection_returns_404(authed_client):
    """AC2: GET /plans/{plan_id}/projection (un-prefixed) returns 404."""
    client, user_id = authed_client
    r = client.get(f"/plans/{user_id}/projection")
    assert r.status_code == 404, (
        f"Expected 404 for un-prefixed /plans/{{id}}/projection, got {r.status_code}."
    )


def test_ac4_projection_works_at_api_prefix(authed_client):
    """AC4: GET /api/plans/{plan_id}/projection returns 200 with ctl/atl/tsb/races/band."""
    client, user_id = authed_client
    r = client.get(f"/api/plans/{user_id}/projection")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    for key in ("ctl", "atl", "tsb", "races", "band"):
        assert key in body, f"Missing key '{key}' in projection response"
