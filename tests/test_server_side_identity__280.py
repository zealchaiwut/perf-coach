"""Tests for issue #280: server-side user identity for workouts, training-log,
readiness, exports, and integration (Strava/Stryd/Google) endpoints.

Verifies:
- Anonymous request → 401 for each endpoint group
- Cross-user isolation: User A token cannot access User B's workout data
- Authenticated same-user access continues to work
- Integration connect/status/disconnect endpoints require auth
"""
import uuid

import httpx
import pytest
from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "hunter2-test-pw-280"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def _make_auth_user(client, suffix):
    name = f"ident280-{suffix}-{_RUN}"
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


# ── 401 anonymous access ──────────────────────────────────────────────────────

class TestAnonymousReturns401:
    def test_workouts_get(self, client):
        assert client.get("/api/workouts", params={"from": "2024-01-01", "to": "2024-01-31"}).status_code == 401

    def test_workouts_post(self, client):
        assert client.post("/api/workouts", json={
            "name": "anon", "workout_date": "2024-01-01", "workout_type": "run"
        }).status_code == 401

    def test_workout_get_by_id(self, client):
        assert client.get(f"/api/workouts/{uuid.uuid4()}").status_code == 401

    def test_workout_patch(self, client):
        assert client.patch(f"/api/workouts/{uuid.uuid4()}", json={"name": "x"}).status_code == 401

    def test_workout_delete(self, client):
        assert client.delete(f"/api/workouts/{uuid.uuid4()}").status_code == 401

    def test_workout_exercises_post(self, client):
        assert client.post(f"/api/workouts/{uuid.uuid4()}/exercises", json={
            "name": "squat", "sets": 3, "reps": 10
        }).status_code == 401

    def test_workout_splits_get(self, client):
        assert client.get(f"/api/workouts/{uuid.uuid4()}/splits").status_code == 401

    def test_training_log_get(self, client):
        assert client.get("/api/training-log").status_code == 401

    def test_readiness_today_get(self, client):
        assert client.get("/api/readiness/today").status_code == 401

    def test_readiness_range_get(self, client):
        assert client.get("/api/readiness", params={"from": "2024-01-01", "to": "2024-01-31"}).status_code == 401

    def test_readiness_compute_post(self, client):
        assert client.post("/api/readiness/compute").status_code == 401

    def test_exports_daily_metrics_get(self, client):
        assert client.get("/api/exports/daily-metrics").status_code == 401

    def test_exports_workouts_get(self, client):
        assert client.get("/api/exports/workouts").status_code == 401

    def test_strava_connect_get(self, client):
        assert client.get("/api/strava/connect").status_code == 401

    def test_strava_status_get(self, client):
        assert client.get("/api/strava/status").status_code == 401

    def test_strava_disconnect_delete(self, client):
        assert client.delete("/api/strava/disconnect").status_code == 401

    def test_stryd_connect_post(self, client):
        assert client.post("/api/stryd/connect", json={"email": "x@x.com", "password": "pw"}).status_code == 401

    def test_stryd_status_get(self, client):
        assert client.get("/api/stryd/status").status_code == 401

    def test_stryd_disconnect_delete(self, client):
        assert client.delete("/api/stryd/disconnect").status_code == 401

    def test_google_connect_get(self, client):
        assert client.get("/api/google/connect").status_code == 401


# ── same-user authenticated access works ─────────────────────────────────────

class TestSameUserWorkoutAccess:
    @pytest.fixture(scope="class")
    def workout_a(self, client, user_a, cookie_a):
        cookies = {"session": cookie_a}
        res = client.post("/api/workouts", json={
            "name": f"workout-a-{_RUN}",
            "workout_date": "2024-03-01",
            "workout_type": "run",
        }, cookies=cookies)
        assert res.status_code == 201, res.text
        wid = res.json()["id"]
        yield wid
        client.delete(f"/api/workouts/{wid}", cookies=cookies)

    def test_workouts_list_authenticated(self, client, cookie_a, workout_a):
        res = client.get("/api/workouts", params={"from": "2024-01-01", "to": "2024-12-31"},
                         cookies={"session": cookie_a})
        assert res.status_code == 200
        ids = [w["id"] for w in res.json()]
        assert workout_a in ids

    def test_workout_get_by_id_authenticated(self, client, cookie_a, workout_a):
        res = client.get(f"/api/workouts/{workout_a}", cookies={"session": cookie_a})
        assert res.status_code == 200

    def test_workout_post_uses_session_user(self, client, user_a, user_b, cookie_a):
        cookies = {"session": cookie_a}
        res = client.post("/api/workouts", json={
            "name": f"session-check-{_RUN}",
            "workout_date": "2024-03-02",
            "workout_type": "bike",
            "user_id": user_b["id"],
        }, cookies=cookies)
        assert res.status_code == 201, res.text
        created = res.json()
        assert created["user_id"] == user_a["id"], "Workout must be saved under session user, not body user_id"
        client.delete(f"/api/workouts/{created['id']}", cookies=cookies)

    def test_training_log_authenticated(self, client, cookie_a):
        res = client.get("/api/training-log", cookies={"session": cookie_a})
        assert res.status_code == 200

    def test_exports_workouts_authenticated(self, client, cookie_a):
        res = client.get("/api/exports/workouts", cookies={"session": cookie_a})
        assert res.status_code == 200

    def test_exports_daily_metrics_authenticated(self, client, cookie_a):
        res = client.get("/api/exports/daily-metrics", cookies={"session": cookie_a})
        assert res.status_code == 200


# ── cross-user isolation ──────────────────────────────────────────────────────

class TestCrossUserIsolation:
    @pytest.fixture(scope="class")
    def workout_b(self, client, user_b, cookie_b):
        cookies = {"session": cookie_b}
        res = client.post("/api/workouts", json={
            "name": f"workout-b-{_RUN}",
            "workout_date": "2024-04-01",
            "workout_type": "strength",
        }, cookies=cookies)
        assert res.status_code == 201, res.text
        wid = res.json()["id"]
        yield wid
        client.delete(f"/api/workouts/{wid}", cookies=cookies)

    def test_workouts_list_does_not_expose_user_b(self, client, cookie_a, workout_b):
        res = client.get("/api/workouts", params={"from": "2024-01-01", "to": "2024-12-31"},
                         cookies={"session": cookie_a})
        assert res.status_code == 200
        ids = [w["id"] for w in res.json()]
        assert workout_b not in ids, "User A must not see User B's workout"

    def test_workout_get_by_id_cross_user_forbidden(self, client, cookie_a, workout_b):
        res = client.get(f"/api/workouts/{workout_b}", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_workout_patch_cross_user_forbidden(self, client, cookie_a, workout_b):
        res = client.patch(f"/api/workouts/{workout_b}", json={"name": "hacked"},
                           cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_workout_delete_cross_user_forbidden(self, client, cookie_a, workout_b):
        res = client.delete(f"/api/workouts/{workout_b}", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_workout_exercises_post_cross_user_forbidden(self, client, cookie_a, workout_b):
        res = client.post(f"/api/workouts/{workout_b}/exercises",
                          json={"name": "squat", "sets": 3, "reps": 10},
                          cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_workout_splits_get_cross_user_forbidden(self, client, cookie_a, workout_b):
        res = client.get(f"/api/workouts/{workout_b}/splits", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_workout_splits_post_cross_user_forbidden(self, client, cookie_a, workout_b):
        res = client.post(f"/api/workouts/{workout_b}/splits",
                          json={"splits": [{"split_index": 0, "distance_km": 1.0, "duration_seconds": 300}]},
                          cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_workout_splits_delete_cross_user_forbidden(self, client, cookie_a, workout_b):
        res = client.delete(f"/api/workouts/{workout_b}/splits", cookies={"session": cookie_a})
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_training_log_does_not_expose_user_b(self, client, cookie_a, workout_b):
        res = client.get("/api/training-log", cookies={"session": cookie_a})
        assert res.status_code == 200
        all_workout_ids = [
            entry["id"]
            for week in res.json().get("weeks", [])
            for entry in week.get("entries", [])
            if entry.get("type") != "rest"
        ]
        assert workout_b not in all_workout_ids, "User A must not see User B's workout in training-log"

    def test_exports_workouts_does_not_expose_user_b(self, client, user_b, cookie_a, workout_b):
        res = client.get("/api/exports/workouts", cookies={"session": cookie_a})
        assert res.status_code == 200
        assert user_b["id"] not in res.text, "User A's workout export must not contain User B's data"
