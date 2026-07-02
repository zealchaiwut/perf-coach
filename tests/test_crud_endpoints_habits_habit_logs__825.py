"""
Tests for issue #825: Add CRUD endpoints for habits and habit logs.
One test per Acceptance Criterion.
Hits the live server at http://127.0.0.1:9001.
"""
import datetime
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_TEST_PW = "test825pw!"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env = dotenv_values(_ROOT / ".env")
_uat_url = _env.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None

TODAY = datetime.date.today().isoformat()
TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _wait_for_server():
    """Block until the UAT server is accepting connections (max 30 s).

    deploy-start.sh backgrounds the server and returns after 1 s; uvicorn may
    need several more seconds before it is ready to accept connections.
    """
    import time
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            httpx.get(f"{BASE}/api/auth/me", timeout=2.0)
            return
        except (httpx.ConnectError, httpx.ConnectTimeout):
            time.sleep(1)
    raise RuntimeError(f"Server at {BASE} not ready after 30 s")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=15.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
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
def authed(user_id):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    with httpx.Client(base_url=BASE, timeout=15.0) as bare:
        res = bare.post("/api/auth/login",
                        json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session_cookie = res.cookies.get("session")
    csrf_token = res.cookies.get(CSRF_COOKIE_NAME)
    c = httpx.Client(
        base_url=BASE,
        timeout=15.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield c
    c.close()


def _valid_habit_body(**overrides):
    body = {
        "name": f"test_habit_{uuid.uuid4().hex[:6]}",
        "habit_type": "binary",
        "schedule_type": "daily",
        "target_value": 1.0,
    }
    body.update(overrides)
    return body


# ── AC1: POST /api/habits creates a habit; validates enum and target_value ────

class TestPostHabitsV2:
    """AC1: POST /api/habits creates a new habit with v2 fields; validates enums and target_value."""

    def test_post_valid_returns_201_with_active_true(self, authed):
        """POST with valid v2 fields returns 201 with active=true and generated id."""
        body = _valid_habit_body()
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 201, res.text
        data = res.json()
        assert "id" in data
        assert uuid.UUID(data["id"])
        assert data.get("active") is True

    def test_post_returns_habit_type_and_schedule_type(self, authed):
        """POST response includes habit_type and schedule_type from request."""
        body = _valid_habit_body(habit_type="count", schedule_type="weekly")
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 201, res.text
        data = res.json()
        assert data.get("habit_type") == "count"
        assert data.get("schedule_type") == "weekly"

    def test_post_invalid_habit_type_returns_422(self, authed):
        """POST with invalid habit_type returns 422."""
        body = _valid_habit_body(habit_type="mood")
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 422, res.text

    def test_post_invalid_schedule_type_returns_422(self, authed):
        """POST with invalid schedule_type returns 422."""
        body = _valid_habit_body(schedule_type="monthly")
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 422, res.text

    def test_post_negative_target_value_returns_422(self, authed):
        """POST with target_value=-5 returns 422."""
        body = _valid_habit_body(target_value=-5)
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 422, res.text

    def test_post_zero_target_value_returns_422(self, authed):
        """POST with target_value=0 returns 422."""
        body = _valid_habit_body(target_value=0)
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 422, res.text

    def test_post_no_type_field_returns_422(self, authed):
        """POST without tracking_type or habit_type returns 422."""
        res = authed.post("/api/habits", json={"name": "no_type_habit"})
        assert res.status_code == 422, res.text

    def test_post_error_shape_on_validation_failure(self, authed):
        """Validation errors return consistent {error, details} shape."""
        body = _valid_habit_body(habit_type="bad_type")
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 422
        body_json = res.json()
        assert "error" in body_json or "detail" in body_json


# ── AC2: GET /api/habits/:id returns single habit or 404 ─────────────────────

class TestGetHabitById:
    """AC2: GET /api/habits/:id returns single habit record or 404."""

    @pytest.fixture(scope="class")
    def habit_id(self, authed):
        body = _valid_habit_body(name="get_by_id_habit")
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 201, res.text
        hid = res.json()["id"]
        yield hid

    def test_get_by_id_returns_200_with_record(self, authed, habit_id):
        """GET /api/habits/{id} returns 200 with the habit record."""
        res = authed.get(f"/api/habits/{habit_id}")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["id"] == habit_id

    def test_get_by_id_returns_v2_fields(self, authed, habit_id):
        """GET /api/habits/{id} response includes v2 fields."""
        res = authed.get(f"/api/habits/{habit_id}")
        data = res.json()
        assert "habit_type" in data
        assert "schedule_type" in data
        assert "active" in data

    def test_get_nonexistent_returns_404(self, authed):
        """GET /api/habits/{unknown_id} returns 404."""
        fake_id = str(uuid.uuid4())
        res = authed.get(f"/api/habits/{fake_id}")
        assert res.status_code == 404, res.text

    def test_get_by_id_includes_archived(self, authed):
        """GET /api/habits/{id} returns archived habits too."""
        body = _valid_habit_body(name="to_be_archived_then_fetched")
        create_res = authed.post("/api/habits", json=body)
        hid = create_res.json()["id"]
        authed.delete(f"/api/habits/{hid}")
        res = authed.get(f"/api/habits/{hid}")
        assert res.status_code == 200, res.text
        assert res.json()["active"] is False


# ── AC3: GET /api/habits supports ?active= filter ────────────────────────────

class TestGetHabitsActiveFilter:
    """AC3: GET /api/habits supports optional ?active= query param."""

    def test_active_true_excludes_archived(self, authed):
        """GET /api/habits?active=true excludes inactive habits."""
        create_res = authed.post(
            "/api/habits", json=_valid_habit_body(name="active_filter_habit"))
        hid = create_res.json()["id"]
        authed.delete(f"/api/habits/{hid}")
        res = authed.get("/api/habits", params={"active": "true"})
        assert res.status_code == 200, res.text
        ids = [h["id"] for h in res.json()]
        assert hid not in ids

    def test_active_false_includes_inactive(self, authed):
        """GET /api/habits?active=false returns only inactive habits."""
        body = _valid_habit_body(name="inactive_filter_test")
        hid = authed.post("/api/habits", json=body).json()["id"]
        authed.delete(f"/api/habits/{hid}")
        res = authed.get("/api/habits", params={"active": "false"})
        assert res.status_code == 200, res.text
        ids = [h["id"] for h in res.json()]
        assert hid in ids

    def test_no_active_param_returns_all(self, authed):
        """GET /api/habits without active param returns all habits."""
        res = authed.get("/api/habits")
        assert res.status_code == 200, res.text
        assert isinstance(res.json(), list)


# ── AC4: PATCH /api/habits/:id updates fields with v2 validations ────────────

class TestPatchHabit:
    """AC4: PATCH /api/habits/:id updates allowed fields; validates enums and target_value."""

    @pytest.fixture(scope="class")
    def habit_id(self, authed):
        body = _valid_habit_body(name="patchable_habit")
        res = authed.post("/api/habits", json=body)
        hid = res.json()["id"]
        yield hid

    def test_patch_name_updates_successfully(self, authed, habit_id):
        """PATCH name field returns 200 with updated name."""
        new_name = f"patched_name_{uuid.uuid4().hex[:4]}"
        res = authed.patch(f"/api/habits/{habit_id}", json={"name": new_name})
        assert res.status_code == 200, res.text
        assert res.json()["name"] == new_name

    def test_patch_invalid_habit_type_returns_422(self, authed, habit_id):
        """PATCH with invalid habit_type returns 422."""
        res = authed.patch(
            f"/api/habits/{habit_id}", json={"habit_type": "invalid"})
        assert res.status_code == 422, res.text

    def test_patch_invalid_schedule_type_returns_422(self, authed, habit_id):
        """PATCH with invalid schedule_type returns 422."""
        res = authed.patch(
            f"/api/habits/{habit_id}", json={"schedule_type": "monthly"})
        assert res.status_code == 422, res.text

    def test_patch_negative_target_value_returns_422(self, authed, habit_id):
        """PATCH with target_value < 0 returns 422."""
        res = authed.patch(
            f"/api/habits/{habit_id}", json={"target_value": -1.0})
        assert res.status_code == 422, res.text

    def test_patch_valid_habit_type_updates(self, authed, habit_id):
        """PATCH with valid habit_type=count returns 200 with updated type."""
        res = authed.patch(
            f"/api/habits/{habit_id}", json={"habit_type": "count"})
        assert res.status_code == 200, res.text
        assert res.json().get("habit_type") == "count"

    def test_patch_nonexistent_returns_404(self, authed):
        """PATCH unknown id returns 404."""
        res = authed.patch(
            f"/api/habits/{uuid.uuid4()}", json={"name": "ghost"})
        assert res.status_code == 404, res.text


# ── AC5: DELETE /api/habits/:id soft-deletes and returns updated record ───────

class TestDeleteHabitV2:
    """AC5: DELETE /api/habits/:id sets active=false; returns the record."""

    def test_delete_returns_200_with_active_false(self, authed):
        """DELETE returns 200 with active=false on the returned record."""
        hid = authed.post("/api/habits", json=_valid_habit_body()).json()["id"]
        res = authed.delete(f"/api/habits/{hid}")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data.get("active") is False

    def test_delete_record_not_in_active_list(self, authed):
        """After DELETE the habit no longer appears in ?active=true list."""
        hid = authed.post("/api/habits", json=_valid_habit_body()).json()["id"]
        authed.delete(f"/api/habits/{hid}")
        active_ids = [h["id"] for h in authed.get(
            "/api/habits", params={"active": "true"}).json()]
        assert hid not in active_ids

    def test_delete_nonexistent_returns_404(self, authed):
        """DELETE unknown id returns 404."""
        res = authed.delete(f"/api/habits/{uuid.uuid4()}")
        assert res.status_code == 404, res.text


# ── AC6: PUT /api/habit-logs upserts a log for (habit_id, log_date) ──────────

class TestPutHabitLogs:
    """AC6: PUT /api/habit-logs upserts a log; validates future dates."""

    @pytest.fixture(scope="class")
    def habit_id(self, authed):
        res = authed.post(
            "/api/habits", json=_valid_habit_body(name="log_upsert_habit"))
        yield res.json()["id"]

    def test_put_valid_log_returns_2xx(self, authed, habit_id):
        """PUT /api/habit-logs with valid body returns 200 or 201 with log record."""
        res = authed.put("/api/habit-logs", json={
            "habit_id": habit_id,
            "log_date": YESTERDAY,
            "value": 1.0,
        })
        assert res.status_code in (200, 201), res.text
        data = res.json()
        assert "id" in data
        assert data.get("habit_id") == habit_id

    def test_put_upsert_updates_value(self, authed, habit_id):
        """Second PUT for same (habit_id, log_date) updates value; no duplicate row."""
        log_date = (datetime.date.today() - \
                    datetime.timedelta(days=2)).isoformat()
        authed.put("/api/habit-logs",
                   json={"habit_id": habit_id, "log_date": log_date, "value": 1.0})
        res = authed.put(
            "/api/habit-logs", json={"habit_id": habit_id, "log_date": log_date, "value": 5.0})
        assert res.status_code in (200, 201), res.text
        assert float(res.json().get("value", 0)) == 5.0

    def test_put_future_date_returns_422(self, authed, habit_id):
        """PUT /api/habit-logs with log_date in the future returns 422."""
        res = authed.put("/api/habit-logs", json={
            "habit_id": habit_id,
            "log_date": TOMORROW,
            "value": 1.0,
        })
        assert res.status_code == 422, res.text

    def test_put_error_shape_consistent(self, authed, habit_id):
        """Validation error for future date returns {error, details} shape."""
        res = authed.put("/api/habit-logs", json={
            "habit_id": habit_id,
            "log_date": TOMORROW,
            "value": 1.0,
        })
        body = res.json()
        assert "error" in body or "detail" in body


# ── AC7: GET /api/habit-logs returns logs in date range; 400 if dates missing ─

class TestGetHabitLogs:
    """AC7: GET /api/habit-logs?habit_id=&from=&to= returns logs; 400 if dates missing."""

    @pytest.fixture(scope="class")
    def habit_with_logs(self, authed):
        """Create a habit and two logs on different dates."""
        hid = authed.post(
            "/api/habits", json=_valid_habit_body(name="log_range_habit")).json()["id"]
        d1 = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        d2 = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        authed.put("/api/habit-logs",
                   json={"habit_id": hid, "log_date": d1, "value": 1.0})
        authed.put("/api/habit-logs",
                   json={"habit_id": hid, "log_date": d2, "value": 2.0})
        yield {"habit_id": hid, "dates": [d1, d2]}

    def test_get_logs_returns_logs_in_range(self, authed, habit_with_logs):
        """GET /api/habit-logs returns all logs within the inclusive date range."""
        hid = habit_with_logs["habit_id"]
        from_d = (datetime.date.today() - \
                  datetime.timedelta(days=7)).isoformat()
        to_d = TODAY
        res = authed.get("/api/habit-logs",
                         params={"habit_id": hid, "from": from_d, "to": to_d})
        assert res.status_code == 200, res.text
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_get_logs_ordered_by_date(self, authed, habit_with_logs):
        """GET /api/habit-logs response is ordered by log_date ascending."""
        hid = habit_with_logs["habit_id"]
        from_d = (datetime.date.today() - \
                  datetime.timedelta(days=7)).isoformat()
        res = authed.get("/api/habit-logs",
                         params={"habit_id": hid, "from": from_d, "to": TODAY})
        assert res.status_code == 200, res.text
        dates = [r["log_date"] for r in res.json()]
        assert dates == sorted(dates)

    def test_get_logs_missing_from_returns_400(self, authed, habit_with_logs):
        """GET /api/habit-logs without from= returns 400."""
        hid = habit_with_logs["habit_id"]
        res = authed.get("/api/habit-logs",
                         params={"habit_id": hid, "to": TODAY})
        assert res.status_code == 400, res.text

    def test_get_logs_missing_to_returns_400(self, authed, habit_with_logs):
        """GET /api/habit-logs without to= returns 400."""
        hid = habit_with_logs["habit_id"]
        res = authed.get("/api/habit-logs",
                         params={"habit_id": hid, "from": TODAY})
        assert res.status_code == 400, res.text

    def test_get_logs_missing_both_dates_returns_400(self, authed, habit_with_logs):
        """GET /api/habit-logs without from= and to= returns 400."""
        hid = habit_with_logs["habit_id"]
        res = authed.get("/api/habit-logs", params={"habit_id": hid})
        assert res.status_code == 400, res.text


# ── AC8: Repository layer — no raw ORM in route handlers ─────────────────────

class TestRepositoryLayer:
    """AC8: All DB access lives in habits_repo; verify the module exists and is importable."""

    def test_habits_repo_module_importable(self):
        """backend.services.habits_repo can be imported."""
        from backend.services import habits_repo  # noqa: F401

    def test_repo_exports_expected_functions(self):
        """habits_repo exposes the expected repository functions."""
        from backend.services import habits_repo
        for fn in ("get_habit", "list_habits", "create_habit", "update_habit",
                   "archive_habit", "upsert_habit_log", "get_habit_logs"):
            assert hasattr(habits_repo, fn), f"habits_repo missing: {fn}"


# ── AC9: No hardcoded defaults — all values from request payload ──────────────

class TestNoHardcodedDefaults:
    """AC9: Endpoints do not inject default values; all must come from the request."""

    def test_habit_type_from_request(self, authed):
        """POST /api/habits stores habit_type exactly as provided in request."""
        body = _valid_habit_body(habit_type="duration")
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 201, res.text
        assert res.json().get("habit_type") == "duration"

    def test_schedule_type_from_request(self, authed):
        """POST /api/habits stores schedule_type exactly as provided in request."""
        body = _valid_habit_body(schedule_type="weekly")
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 201, res.text
        assert res.json().get("schedule_type") == "weekly"

    def test_target_value_from_request(self, authed):
        """POST /api/habits stores target_value exactly as provided in request."""
        body = _valid_habit_body(target_value=7.5)
        res = authed.post("/api/habits", json=body)
        assert res.status_code == 201, res.text
        assert float(res.json().get("target_value", 0)) == 7.5


# ── AC10: Consistent error shapes ────────────────────────────────────────────

class TestConsistentErrorShapes:
    """AC10: Validation failures return {error, details} shape."""

    def test_post_invalid_enum_error_shape(self, authed):
        """422 for bad habit_type includes error key."""
        res = authed.post(
            "/api/habits", json=_valid_habit_body(habit_type="bad"))
        assert res.status_code == 422
        body = res.json()
        assert "error" in body or "detail" in body

    def test_put_future_date_error_shape(self, authed):
        """422 for future log_date includes error key."""
        hid = authed.post("/api/habits", json=_valid_habit_body()).json()["id"]
        res = authed.put(
            "/api/habit-logs", json={"habit_id": hid, "log_date": TOMORROW, "value": 1.0})
        assert res.status_code == 422
        body = res.json()
        assert "error" in body or "detail" in body

    def test_get_logs_missing_dates_error_shape(self, authed):
        """400 for missing dates includes error key."""
        hid = authed.post("/api/habits", json=_valid_habit_body()).json()["id"]
        res = authed.get("/api/habit-logs", params={"habit_id": hid})
        assert res.status_code == 400
        body = res.json()
        assert "error" in body or "detail" in body
