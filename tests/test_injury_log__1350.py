"""Tests for issue #1350: Injury / illness / niggle log CRUD API (runs against UAT)

AC coverage:
- CRUD: POST, GET list (with date range), GET active, PATCH (incl. close), DELETE
- Active filter: null ended_on only
- Validation errors: 422 for bad kind, bad severity, bad dates
- Cross-user isolation: user A cannot see user B's entries
"""
import os
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

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "test1350pw!"
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _require_engine():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping live-server test")


def _make_user(name: str) -> str:
    _require_engine()
    r = httpx.post(f"{BASE_URL}/api/users", json={"name": name}, cookies=_admin_cookies(), timeout=10.0)
    assert r.status_code == 201, f"Failed to create user: {r.text}"
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    return uid


def _delete_user(uid: str):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        if u:
            db.delete(u)
            db.commit()


def _make_client(uid: str) -> httpx.Client:
    _require_engine()
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        name = u.name
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        res = bare.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, f"Login failed: {res.text}"
    session_cookie = res.cookies.get("session")
    csrf_token = res.cookies.get(CSRF_COOKIE_NAME)
    return httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )


@pytest.fixture(scope="module")
def user_id():
    _require_engine()
    uid = _make_user(f"tester1350_{uuid.uuid4().hex[:8]}")
    yield uid
    _delete_user(uid)


@pytest.fixture(scope="module")
def client(user_id):
    _require_engine()
    c = _make_client(user_id)
    yield c
    c.close()


@pytest.fixture(scope="module")
def other_user_id():
    _require_engine()
    uid = _make_user(f"tester1350b_{uuid.uuid4().hex[:8]}")
    yield uid
    _delete_user(uid)


@pytest.fixture(scope="module")
def other_client(other_user_id):
    _require_engine()
    c = _make_client(other_user_id)
    yield c
    c.close()


# ── AC: POST creates an entry ────────────────────────────────────────────────

def test_injury_log__create_niggle(client):
    r = client.post("/api/injury-log", json={
        "kind": "niggle",
        "body_area": "left_calf",
        "severity": 1,
        "started_on": "2026-07-10",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["id"] is not None
    assert data["kind"] == "niggle"
    assert data["body_area"] == "left_calf"
    assert data["severity"] == 1
    assert data["started_on"] == "2026-07-10"
    assert data["ended_on"] is None


def test_injury_log__create_illness(client):
    r = client.post("/api/injury-log", json={
        "kind": "illness",
        "severity": 2,
        "started_on": "2026-07-09",
        "notes": "mild cold",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "illness"
    assert data["severity"] == 2
    assert data["body_area"] is None
    assert data["notes"] == "mild cold"


def test_injury_log__create_injury(client):
    r = client.post("/api/injury-log", json={
        "kind": "injury",
        "body_area": "right_knee",
        "severity": 3,
        "started_on": "2026-07-01",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "injury"
    assert data["severity"] == 3


# ── AC: GET list with date range ─────────────────────────────────────────────

def test_injury_log__list_all(client):
    r = client.get("/api/injury-log")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 3


def test_injury_log__list_date_range(client):
    r = client.get("/api/injury-log", params={"from": "2026-07-09", "to": "2026-07-10"})
    assert r.status_code == 200
    data = r.json()
    kinds = {e["kind"] for e in data}
    assert "niggle" in kinds
    assert "illness" in kinds
    for entry in data:
        assert entry["started_on"] >= "2026-07-09"
        assert entry["started_on"] <= "2026-07-10"


# ── AC: GET active (null ended_on only) ─────────────────────────────────────

def test_injury_log__active_filter(client):
    r = client.get("/api/injury-log/active")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    for entry in data:
        assert entry["ended_on"] is None


def test_injury_log__active_excludes_closed(client):
    # Create an entry and immediately close it
    create = client.post("/api/injury-log", json={
        "kind": "niggle",
        "body_area": "shoulder",
        "severity": 1,
        "started_on": "2026-07-05",
        "ended_on": "2026-07-06",
    })
    assert create.status_code == 201
    entry_id = create.json()["id"]

    active = client.get("/api/injury-log/active")
    assert r.status_code == 200 if (r := active) else True
    active_ids = {e["id"] for e in active.json()}
    assert entry_id not in active_ids


# ── AC: PATCH (partial update + close) ──────────────────────────────────────

def test_injury_log__patch_notes(client):
    create = client.post("/api/injury-log", json={
        "kind": "niggle",
        "body_area": "left_calf",
        "severity": 1,
        "started_on": "2026-07-10",
    })
    assert create.status_code == 201
    entry_id = create.json()["id"]

    r = client.patch(f"/api/injury-log/{entry_id}", json={"notes": "getting better"})
    assert r.status_code == 200
    data = r.json()
    assert data["notes"] == "getting better"
    assert data["severity"] == 1  # unchanged


def test_injury_log__patch_close(client):
    # AC: PATCH with ended_on closes the entry (marks resolved)
    create = client.post("/api/injury-log", json={
        "kind": "niggle",
        "body_area": "left_calf",
        "severity": 1,
        "started_on": "2026-07-10",
    })
    assert create.status_code == 201
    entry_id = create.json()["id"]

    # Confirm it's active before closing
    active_before = client.get("/api/injury-log/active").json()
    assert any(e["id"] == entry_id for e in active_before)

    r = client.patch(f"/api/injury-log/{entry_id}", json={"ended_on": "2026-07-11"})
    assert r.status_code == 200
    data = r.json()
    assert data["ended_on"] == "2026-07-11"

    # Now it must not appear in active list
    active_after = client.get("/api/injury-log/active").json()
    assert not any(e["id"] == entry_id for e in active_after)


def test_injury_log__patch_not_found(client):
    r = client.patch(
        f"/api/injury-log/{uuid.uuid4()}",
        json={"notes": "x"},
    )
    assert r.status_code == 404


# ── AC: DELETE ───────────────────────────────────────────────────────────────

def test_injury_log__delete(client):
    create = client.post("/api/injury-log", json={
        "kind": "illness",
        "severity": 1,
        "started_on": "2026-07-08",
    })
    assert create.status_code == 201
    entry_id = create.json()["id"]

    r = client.delete(f"/api/injury-log/{entry_id}")
    assert r.status_code == 204

    # Confirm it's gone from list
    lst = client.get("/api/injury-log").json()
    assert not any(e["id"] == entry_id for e in lst)


def test_injury_log__delete_not_found(client):
    r = client.delete(f"/api/injury-log/{uuid.uuid4()}")
    assert r.status_code == 404


# ── AC: Validation errors (422) ──────────────────────────────────────────────

def test_injury_log__invalid_kind(client):
    r = client.post("/api/injury-log", json={
        "kind": "sprain",  # not a valid kind
        "severity": 1,
        "started_on": "2026-07-10",
    })
    assert r.status_code == 422


def test_injury_log__invalid_severity_zero(client):
    r = client.post("/api/injury-log", json={
        "kind": "niggle",
        "severity": 0,  # must be 1-3
        "started_on": "2026-07-10",
    })
    assert r.status_code == 422


def test_injury_log__invalid_severity_four(client):
    r = client.post("/api/injury-log", json={
        "kind": "niggle",
        "severity": 4,  # must be 1-3
        "started_on": "2026-07-10",
    })
    assert r.status_code == 422


def test_injury_log__invalid_date_format(client):
    r = client.post("/api/injury-log", json={
        "kind": "niggle",
        "severity": 1,
        "started_on": "07-10-2026",  # wrong format
    })
    assert r.status_code == 422


def test_injury_log__missing_required_fields(client):
    # kind and started_on are required
    r = client.post("/api/injury-log", json={"severity": 1})
    assert r.status_code == 422


def test_injury_log__ended_before_started(client):
    r = client.post("/api/injury-log", json={
        "kind": "niggle",
        "severity": 1,
        "started_on": "2026-07-10",
        "ended_on": "2026-07-09",  # before started
    })
    assert r.status_code == 422


# ── AC: Cross-user isolation ─────────────────────────────────────────────────

def test_injury_log__cross_user_isolation(client, other_client):
    # User A creates an entry
    create = client.post("/api/injury-log", json={
        "kind": "injury",
        "body_area": "ankle",
        "severity": 2,
        "started_on": "2026-07-10",
    })
    assert create.status_code == 201
    entry_id = create.json()["id"]

    # User B cannot see it in their list
    other_list = other_client.get("/api/injury-log").json()
    assert not any(e["id"] == entry_id for e in other_list)

    # User B gets 404 on direct access
    r = other_client.patch(f"/api/injury-log/{entry_id}", json={"notes": "hacked"})
    assert r.status_code == 404

    r = other_client.delete(f"/api/injury-log/{entry_id}")
    assert r.status_code == 404


def test_injury_log__active_cross_user_isolation(client, other_client):
    # User A's active entries are not visible to user B
    client_active = client.get("/api/injury-log/active").json()
    other_active = other_client.get("/api/injury-log/active").json()
    client_ids = {e["id"] for e in client_active}
    other_ids = {e["id"] for e in other_active}
    assert client_ids.isdisjoint(other_ids)
