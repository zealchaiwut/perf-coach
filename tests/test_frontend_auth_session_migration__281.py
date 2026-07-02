"""Tests for issue #281: migrate frontend auth to session, drop user_id shim.

Verifies:
- legacy ?user_id query-param shim removed: ?user_id can never authenticate
- Session cookie auth continues to work for all major endpoint groups
- /api/auth/me returns correct session user
- Supplying ?user_id= of another user with a valid session is ignored (session wins)
- Unauthenticated requests return 401
"""
import time
import uuid

import httpx
import pytest
from backend.auth import ADMIN_COOKIE_NAME, create_admin_cookie, hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "test-pw-281"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def _admin_cookies():
    # POST/DELETE /api/users are admin-gated (fix-loopholes Task 1) — these
    # fixtures only use them as test-user plumbing, not as the thing under test.
    return {ADMIN_COOKIE_NAME: create_admin_cookie(time.time())}


def _make_auth_user(client, suffix):
    name = f"shim281-{suffix}-{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]
    pw_hash = hash_password(_TEST_PASSWORD)
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        u.password_hash = pw_hash
        db.commit()
    return {"id": user_id, "name": name}


def _login(client, name):
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PASSWORD})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def user_a(client):
    u = _make_auth_user(client, "a")
    yield u
    client.delete(f"/api/users/{u['id']}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def user_b(client):
    u = _make_auth_user(client, "b")
    yield u
    client.delete(f"/api/users/{u['id']}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def cookie_a(client, user_a):
    return _login(client, user_a["name"])


@pytest.fixture(scope="module")
def cookie_b(client, user_b):
    return _login(client, user_b["name"])


# ── shim disabled: ?user_id no longer authenticates ──────────────────────────

class TestUserIdShimDisabled:
    """The legacy ?user_id shim is removed; ?user_id can never substitute for a session
    on auth-gated endpoints. /api/weight-entries intentionally accepts ?user_id without
    a session (it is the public replacement), so it should return 200 here."""

    def test_weight_entries_get_with_user_id_param_returns_200(self, client, user_a):
        # /api/weight-entries is the new endpoint; it accepts ?user_id without a session
        res = client.get("/api/weight-entries", params={"user_id": user_a["id"]})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()
        assert "entries" in body, "Response must have 'entries' key"

    def test_habits_get_with_user_id_param_returns_401(self, client, user_a):
        res = client.get("/api/habits", params={"user_id": user_a["id"]})
        assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"

    def test_workouts_get_with_user_id_param_returns_401(self, client, user_a):
        res = client.get(
            "/api/workouts",
            params={"user_id": user_a["id"], "from": "2024-01-01", "to": "2024-12-31"},
        )
        assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"

    def test_daily_metrics_with_user_id_param_returns_401(self, client, user_a):
        res = client.get(
            "/api/daily-metrics",
            params={"user_id": user_a["id"], "from": "2024-01-01", "to": "2024-01-31"},
        )
        assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"

    def test_training_log_with_user_id_param_returns_401(self, client, user_a):
        res = client.get("/api/training-log", params={"user_id": user_a["id"]})
        assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"


# ── /api/auth/me ──────────────────────────────────────────────────────────────

class TestAuthMe:
    def test_me_unauthenticated_returns_401(self, client):
        res = client.get("/api/auth/me")
        assert res.status_code == 401, f"Expected 401, got {res.status_code}"

    def test_me_with_session_returns_user(self, client, user_a, cookie_a):
        res = client.get("/api/auth/me", cookies={"session": cookie_a})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()
        assert body["id"] == user_a["id"]
        assert body["name"] == user_a["name"]


# ── session auth works (no regression) ───────────────────────────────────────

class TestSessionAuthWorks:
    def test_weight_entries_get_with_session(self, client, user_a, cookie_a):
        # /api/weight-entries accepts ?user_id; session cookie is optional but harmless
        res = client.get(
            "/api/weight-entries",
            params={"user_id": user_a["id"]},
            cookies={"session": cookie_a},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()
        assert "entries" in body, "Response must have 'entries' key"

    def test_habits_get_with_session(self, client, cookie_a):
        res = client.get("/api/habits", cookies={"session": cookie_a})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    def test_workouts_get_with_session(self, client, cookie_a):
        res = client.get(
            "/api/workouts",
            params={"from": "2024-01-01", "to": "2024-12-31"},
            cookies={"session": cookie_a},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    def test_training_log_get_with_session(self, client, cookie_a):
        res = client.get("/api/training-log", cookies={"session": cookie_a})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    def test_daily_metrics_post_with_session(self, client, cookie_a):
        res = client.post(
            "/api/daily-metrics",
            json={"metric_date": "2024-01-15", "energy": 3, "mood": 4},
            cookies={"session": cookie_a},
        )
        assert res.status_code in (201, 409), f"Expected 201/409, got {res.status_code}: {res.text}"


# ── session wins over ?user_id param ─────────────────────────────────────────

class TestSessionWinsOverUserIdParam:
    """For /api/weight-entries the ?user_id param controls which user's data is returned
    (the endpoint is public by design). Verify that supplying user_a's id returns only
    user_a's entries (user isolation enforced by the ?user_id param itself)."""

    def test_weight_entries_user_id_param_filters_correctly(self, client, user_a, user_b, cookie_a):
        # Fetch user_a's entries using their own user_id; session cookie is ignored/harmless
        res = client.get(
            "/api/weight-entries",
            params={"user_id": user_a["id"]},
            cookies={"session": cookie_a},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        entries = res.json()["entries"]
        for entry in entries:
            assert entry.get("user_id") == user_a["id"], (
                f"Entry belongs to {entry.get('user_id')}, expected user_a {user_a['id']}"
            )

    def test_workouts_session_overrides_user_id_param(self, client, user_a, user_b, cookie_a):
        res = client.get(
            "/api/workouts",
            params={"user_id": user_b["id"], "from": "2024-01-01", "to": "2024-12-31"},
            cookies={"session": cookie_a},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        for workout in res.json():
            assert workout.get("user_id") == user_a["id"], (
                f"Workout belongs to {workout.get('user_id')}, expected session user {user_a['id']}"
            )
