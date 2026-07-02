"""Tests for fix-loopholes Task 1: /api/users CRUD must be admin-gated.

GET/POST/PATCH/DELETE /api/users had no auth at all — anyone could enumerate
every user (with Strava/Stryd connection status), create users, rename any
user, or delete any user (cascading all their data). All four are now gated
behind require_admin, matching the existing /api/admin/users pattern.

tests/conftest.py bypasses require_admin globally so the ~90 other test
files that use unauthenticated POST /api/users as fixture plumbing keep
working — these tests explicitly pop that override to exercise the real
auth behavior.
"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth import ADMIN_COOKIE_NAME, create_admin_cookie, require_admin
from backend.main import app

_client = TestClient(app)


@pytest.fixture(autouse=True)
def _real_require_admin():
    """Pop the conftest bypass so these tests exercise the actual dependency."""
    app.dependency_overrides.pop(require_admin, None)
    yield
    from tests.conftest import _admin_bypass
    app.dependency_overrides[require_admin] = _admin_bypass


def _admin_cookies():
    token = create_admin_cookie(time.time())
    return {ADMIN_COOKIE_NAME: token}


# ── Unauthenticated: every verb must be rejected ────────────────────────────


def test_get_users_requires_admin_when_unauthenticated():
    res = _client.get("/api/users", headers={"Accept": "application/json"})
    assert res.status_code in (401, 403)


def test_post_users_requires_admin_when_unauthenticated():
    res = _client.post(
        "/api/users",
        json={"name": "loophole-test-" + uuid.uuid4().hex[:8]},
        headers={"Accept": "application/json"},
    )
    assert res.status_code in (401, 403)


def test_patch_users_requires_admin_when_unauthenticated():
    res = _client.patch(
        f"/api/users/{uuid.uuid4()}",
        json={"name": "whatever"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code in (401, 403)


def test_delete_users_requires_admin_when_unauthenticated():
    res = _client.delete(
        f"/api/users/{uuid.uuid4()}",
        headers={"Accept": "application/json"},
    )
    assert res.status_code in (401, 403)


# ── With a valid admin cookie: each verb reaches its real handler ──────────


def test_get_users_works_with_admin_cookie():
    res = _client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_post_users_works_with_admin_cookie():
    name = "loophole-test-" + uuid.uuid4().hex[:8]
    res = _client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == name
    # Cleanup via the same admin-gated DELETE.
    _client.delete(f"/api/users/{body['id']}", cookies=_admin_cookies())


def test_patch_users_works_with_admin_cookie():
    name = "loophole-test-" + uuid.uuid4().hex[:8]
    created = _client.post("/api/users", json={"name": name}, cookies=_admin_cookies()).json()
    new_name = "loophole-renamed-" + uuid.uuid4().hex[:8]
    res = _client.patch(
        f"/api/users/{created['id']}",
        json={"name": new_name},
        cookies=_admin_cookies(),
    )
    assert res.status_code == 200
    assert res.json()["name"] == new_name
    _client.delete(f"/api/users/{created['id']}", cookies=_admin_cookies())


def test_delete_users_works_with_admin_cookie():
    name = "loophole-test-" + uuid.uuid4().hex[:8]
    created = _client.post("/api/users", json={"name": name}, cookies=_admin_cookies()).json()
    res = _client.delete(f"/api/users/{created['id']}", cookies=_admin_cookies())
    assert res.status_code == 204
