"""Tests for issue #256: workout_feel table schema and migration.

Verifies: model import, rest-day entry (workout_id=NULL, rpe=NULL),
no unique constraint on (user_id, feel_date), SET NULL on workout delete,
CASCADE delete on user delete.
"""
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_RUN = str(uuid.uuid4())[:8]
_DATE_A = "2025-10-01"
_DATE_B = "2025-10-02"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    name = f"FeelSchema_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next(u for u in users if u["name"] == name)
    return u["id"]


@pytest.fixture(scope="module")
def workout_id(client, user_id):
    res = client.post(
        "/api/workouts",
        json={"user_id": user_id, "workout_date": _DATE_A,
              "name": f"SchemaWO_{_RUN}", "workout_type": "run"},
    )
    assert res.status_code == 201
    return res.json()["id"]


# ── AC: model import ──────────────────────────────────────────────────────────

def test_workout_feel_import():
    from backend.models import WorkoutFeel
    assert WorkoutFeel.__tablename__ == "workout_feel"


# ── AC: rest-day entry (workout_id=NULL, rpe=NULL) ───────────────────────────

def test_rest_day_entry_201(client, user_id):
    """workout_id=NULL and rpe_1_to_10=NULL accepted when notes provided."""
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": _DATE_A, "notes": "rest day"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["workout_id"] is None
    assert body["rpe_1_to_10"] is None
    assert body["notes"] == "rest day"


# ── AC: no unique constraint on (user_id, feel_date) ─────────────────────────

def test_multiple_entries_same_day_no_409(client, user_id):
    """Two entries for the same user+date both succeed."""
    payload = {"user_id": user_id, "feel_date": _DATE_B, "notes": "entry 1"}
    r1 = client.post("/api/feel", json=payload)
    assert r1.status_code == 201

    payload2 = {"user_id": user_id, "feel_date": _DATE_B, "notes": "entry 2"}
    r2 = client.post("/api/feel", json=payload)
    assert r2.status_code == 201

    res = client.get("/api/feel", params={"user_id": user_id, "from": _DATE_B, "to": _DATE_B})
    assert res.status_code == 200
    assert res.json()["count"] >= 2


# ── AC: SET NULL when workout deleted ────────────────────────────────────────

@pytest.fixture(scope="module")
def linked_feel_id(client, user_id, workout_id):
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": _DATE_A,
              "workout_id": workout_id, "rpe_1_to_10": 8},
    )
    assert res.status_code == 201
    return res.json()["id"]


def test_delete_workout_sets_null_on_feel(client, user_id, workout_id, linked_feel_id):
    """Deleting the parent workout preserves the feel row; workout_id becomes NULL."""
    del_res = client.delete(f"/api/workouts/{workout_id}")
    assert del_res.status_code == 204

    entries = client.get("/api/feel", params={"user_id": user_id}).json()["entries"]
    matched = [e for e in entries if e["id"] == linked_feel_id]
    assert matched, "feel entry must still exist after workout deletion"
    assert matched[0]["workout_id"] is None


# ── AC: CASCADE delete when user deleted ─────────────────────────────────────

def test_cascade_delete_user_removes_feel_rows(client):
    """Deleting a user cascades and removes all their feel rows."""
    from backend.db import engine
    from backend.models import WorkoutFeel
    from sqlalchemy.orm import Session as DbSession
    import uuid as _uuid

    # create isolated user
    cascade_name = f"CascadeUser_{_RUN}"
    res = client.post("/api/users", json={"name": cascade_name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next(u for u in users if u["name"] == cascade_name)
    uid_str = u["id"]

    # post two feel entries
    for i in range(2):
        r = client.post(
            "/api/feel",
            json={"user_id": uid_str, "feel_date": f"2025-09-0{i + 1}", "notes": f"entry {i}"},
        )
        assert r.status_code == 201

    # confirm entries exist in DB
    uid = _uuid.UUID(uid_str)
    with DbSession(engine) as session:
        before = session.query(WorkoutFeel).filter(WorkoutFeel.user_id == uid).count()
    assert before == 2

    # delete user
    del_res = client.delete(f"/api/users/{uid_str}", cookies=_admin_cookies())
    assert del_res.status_code == 204

    # confirm cascade: feel rows are gone
    with DbSession(engine) as session:
        after = session.query(WorkoutFeel).filter(WorkoutFeel.user_id == uid).count()
    assert after == 0, f"Expected 0 feel rows after user delete, found {after}"
