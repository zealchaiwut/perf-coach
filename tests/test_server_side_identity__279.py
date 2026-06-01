"""Tests for issue #279: server-side user identity for weight, habits, habit-logs,
daily-metrics, and feel endpoints.

Verifies:
- Anonymous request → 401 for each endpoint group
- Cross-user isolation: User A token + User B's resource → 403/404, not User B's data
- Authenticated same-user access continues to work
"""
import uuid

import httpx
import pytest
from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "hunter2-test-pw"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def _make_auth_user(client, suffix):
    name = f"ident-{suffix}-{_RUN}"
    res = client.post("/api/users", json={"name": name})
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
    client.delete(f"/api/users/{u['id']}")


@pytest.fixture(scope="module")
def user_b(client):
    u = _make_auth_user(client, "b")
    yield u
    client.delete(f"/api/users/{u['id']}")


@pytest.fixture(scope="module")
def cookie_a(client, user_a):
    return _login(client, user_a["name"])


@pytest.fixture(scope="module")
def cookie_b(client, user_b):
    return _login(client, user_b["name"])


# ── 401 anonymous access ──────────────────────────────────────────────────────

class TestAnonymousReturns401:
    def test_weight_get(self, client):
        assert client.get("/api/weight").status_code == 401

    def test_weight_post(self, client):
        assert client.post("/api/weight", json={"weight_kg": 70, "recorded_date": "2025-01-01"}).status_code == 401

    def test_habits_get(self, client):
        assert client.get("/api/habits").status_code == 401

    def test_habits_post(self, client):
        assert client.post("/api/habits", json={"name": "anon"}).status_code == 401

    def test_habit_logs_get(self, client):
        assert client.get("/api/habits/logs", params={"from": "2025-01-01", "to": "2025-01-31"}).status_code == 401

    def test_habit_logs_post(self, client):
        assert client.post("/api/habits/logs", json={"habit_id": str(uuid.uuid4()), "logged_date": "2025-01-01"}).status_code == 401

    def test_daily_metrics_get(self, client):
        assert client.get("/api/daily-metrics").status_code == 401

    def test_daily_metrics_post(self, client):
        assert client.post("/api/daily-metrics", json={"metric_date": "2025-01-01", "energy": 7}).status_code == 401

    def test_feel_get(self, client):
        assert client.get("/api/feel").status_code == 401

    def test_feel_post(self, client):
        assert client.post("/api/feel", json={"feel_date": "2025-01-01", "notes": "anon"}).status_code == 401


# ── same-user authenticated access works ─────────────────────────────────────

class TestSameUserAccess:
    def test_weight_crud(self, client, user_a, cookie_a):
        cookies = {"session": cookie_a}
        res = client.post("/api/weight", json={"weight_kg": 65.0, "recorded_date": "2024-03-01"}, cookies=cookies)
        assert res.status_code == 201, res.text
        entry_id = res.json()["id"]

        rows = client.get("/api/weight", cookies=cookies).json()
        assert any(r["id"] == entry_id for r in rows)

        del_res = client.delete(f"/api/weight/{entry_id}", cookies=cookies)
        assert del_res.status_code == 204

    def test_habits_crud(self, client, cookie_a):
        cookies = {"session": cookie_a}
        res = client.post("/api/habits", json={"name": f"h-{_RUN}"}, cookies=cookies)
        assert res.status_code == 201, res.text
        habit_id = res.json()["id"]

        rows = client.get("/api/habits", cookies=cookies).json()
        assert any(r["id"] == habit_id for r in rows)

        del_res = client.delete(f"/api/habits/{habit_id}", cookies=cookies)
        assert del_res.status_code == 204

    def test_daily_metrics_post_uses_authed_user(self, client, user_a, cookie_a):
        cookies = {"session": cookie_a}
        res = client.post(
            "/api/daily-metrics",
            json={"metric_date": "2024-04-01", "energy": 4, "user_id": user_a["id"]},
            cookies=cookies,
        )
        assert res.status_code in (201, 409), res.text

    def test_feel_post_uses_authed_user(self, client, cookie_a):
        cookies = {"session": cookie_a}
        res = client.post("/api/feel", json={"feel_date": "2024-04-02", "notes": "test"}, cookies=cookies)
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["user_id"] is not None


# ── cross-user isolation ──────────────────────────────────────────────────────

class TestCrossUserIsolation:
    @pytest.fixture(scope="class")
    def weight_entry_b(self, client, user_b, cookie_b):
        res = client.post(
            "/api/weight",
            json={"weight_kg": 80.0, "recorded_date": "2024-05-01"},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 201, res.text
        entry_id = res.json()["id"]
        yield entry_id
        client.delete(f"/api/weight/{entry_id}", cookies={"session": cookie_b})

    @pytest.fixture(scope="class")
    def habit_b(self, client, cookie_b):
        res = client.post("/api/habits", json={"name": f"hb-{_RUN}"}, cookies={"session": cookie_b})
        assert res.status_code == 201, res.text
        habit_id = res.json()["id"]
        yield habit_id
        client.delete(f"/api/habits/{habit_id}", cookies={"session": cookie_b})

    @pytest.fixture(scope="class")
    def habit_log_b(self, client, habit_b, cookie_b):
        res = client.post(
            "/api/habits/logs",
            json={"habit_id": habit_b, "logged_date": "2024-05-01"},
            cookies={"session": cookie_b},
        )
        assert res.status_code == 201, res.text
        log_id = res.json()["id"]
        yield log_id
        # cleanup may already be deleted; ignore 404
        client.delete(f"/api/habits/logs/{log_id}", cookies={"session": cookie_b})

    @pytest.fixture(scope="class")
    def feel_b(self, client, cookie_b):
        res = client.post("/api/feel", json={"feel_date": "2024-05-02", "notes": "b-note"}, cookies={"session": cookie_b})
        assert res.status_code == 201, res.text
        feel_id = res.json()["id"]
        yield feel_id
        client.delete(f"/api/feel/{feel_id}", cookies={"session": cookie_b})

    def test_weight_get_does_not_expose_user_b_data(self, client, user_b, cookie_a, weight_entry_b):
        """User A's GET /weight returns only A's entries; B's entry is absent."""
        rows = client.get("/api/weight", cookies={"session": cookie_a}).json()
        assert not any(r["id"] == weight_entry_b for r in rows), "User B's weight entry must not be visible to User A"

    def test_weight_post_ignores_body_user_id(self, client, user_a, user_b, cookie_a, cookie_b):
        """POST /weight with user_b's id in body still creates entry for user_a."""
        res = client.post(
            "/api/weight",
            json={"weight_kg": 68.0, "recorded_date": "2024-05-10", "user_id": user_b["id"]},
            cookies={"session": cookie_a},
        )
        assert res.status_code in (201, 409), res.text
        if res.status_code == 201:
            entry_id = res.json()["id"]
            rows_a = client.get("/api/weight", cookies={"session": cookie_a}).json()
            assert any(r["id"] == entry_id for r in rows_a), "Entry should appear under User A"
            rows_b = client.get("/api/weight", cookies={"session": cookie_b}).json()
            assert not any(r["id"] == entry_id for r in rows_b), "Entry must not appear under User B"
            client.delete(f"/api/weight/{entry_id}", cookies={"session": cookie_a})

    def test_weight_delete_cross_user_forbidden(self, client, cookie_a, weight_entry_b):
        """User A cannot delete User B's weight entry."""
        res = client.delete(f"/api/weight/{weight_entry_b}", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_habits_get_does_not_expose_user_b(self, client, habit_b, cookie_a):
        """User A's GET /habits does not return User B's habit."""
        rows = client.get("/api/habits", cookies={"session": cookie_a}).json()
        assert not any(r["id"] == habit_b for r in rows)

    def test_habit_patch_cross_user_forbidden(self, client, habit_b, cookie_a):
        res = client.patch(f"/api/habits/{habit_b}", json={"name": "hacked"}, cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_habit_delete_cross_user_forbidden(self, client, habit_b, cookie_a):
        res = client.delete(f"/api/habits/{habit_b}", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_habit_log_delete_cross_user_forbidden(self, client, habit_log_b, cookie_a):
        """User A cannot delete User B's habit log (UAT step 5)."""
        res = client.delete(f"/api/habits/logs/{habit_log_b}", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_daily_metrics_post_ignores_body_user_id(self, client, user_a, user_b, cookie_a):
        """POST /daily-metrics with user_b id in body saves under user_a (UAT step 6)."""
        date = "2024-06-01"
        res = client.post(
            "/api/daily-metrics",
            json={"metric_date": date, "energy": 4, "user_id": user_b["id"]},
            cookies={"session": cookie_a},
        )
        if res.status_code == 409:
            pytest.skip("entry already exists for this date, skipping")
        assert res.status_code == 201, res.text
        created = res.json()
        assert created["user_id"] == user_a["id"], "Metric must be saved under User A, not User B"

    def test_daily_metrics_get_does_not_expose_user_b(self, client, user_a, user_b, cookie_a):
        """User A calling GET /daily-metrics does not see User B's metrics."""
        with Session(engine) as db:
            from backend.models import DailyMetric
            import datetime
            row = db.query(DailyMetric).filter(DailyMetric.user_id == uuid.UUID(user_b["id"])).first()
        if row is None:
            pytest.skip("User B has no metrics to test isolation against")
        rows = client.get("/api/daily-metrics", cookies={"session": cookie_a}).json()
        assert not any(r["user_id"] == user_b["id"] for r in rows)

    def test_feel_get_does_not_expose_user_b(self, client, feel_b, cookie_a):
        """User A GET /feel does not return User B's feel entry (UAT step 7)."""
        entries = client.get("/api/feel", cookies={"session": cookie_a}).json()["entries"]
        assert not any(e["id"] == feel_b for e in entries)

    def test_feel_post_ignores_body_user_id(self, client, user_a, user_b, cookie_a):
        """POST /feel with user_b id in body creates entry under user_a."""
        res = client.post(
            "/api/feel",
            json={"feel_date": "2024-06-02", "notes": "owned by a", "user_id": user_b["id"]},
            cookies={"session": cookie_a},
        )
        assert res.status_code == 201, res.text
        assert res.json()["user_id"] == user_a["id"]
        feel_id = res.json()["id"]
        client.delete(f"/api/feel/{feel_id}", cookies={"session": cookie_a})

    def test_feel_delete_cross_user_forbidden(self, client, feel_b, cookie_a):
        res = client.delete(f"/api/feel/{feel_b}", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_feel_patch_cross_user_forbidden(self, client, feel_b, cookie_a):
        res = client.patch(f"/api/feel/{feel_b}", json={"notes": "hacked"}, cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"
