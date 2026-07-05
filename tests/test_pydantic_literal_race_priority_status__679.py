"""Tests for issue #679: Add Pydantic Literal validation for race priority and status fields.

Acceptance criteria verified:
- AC1: _RaceCreateBody.priority is Optional[Literal["A", "B", "C"]] — rejects values outside that set at parse time.
- AC2: _RaceCreateBody.status is Optional[Literal["planned", "done", "abandoned"]] — rejects values outside that set at parse time.
- AC3: _RaceUpdateBody.priority and .status have the same Literal constraints.
- AC4: POST to race create with "priority": "Z" returns 422 identifying priority as invalid (not 500).
- AC5: PATCH/PUT to race update with "status": "invalid" returns 422 identifying status as invalid (not 500).
- AC6: Valid values ("A"/"B"/"C" for priority; "planned"/"done"/"abandoned" for status) are accepted and persisted.

Runs against the live UAT server at UAT_BASE_URL (default http://127.0.0.1:9001).
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
from backend.models import Race as _Race, User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "races679-test-pw"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = (
    _env_vals.get("DATABASE_URL_UAT")
    or os.environ.get("DATABASE_URL_UAT")
)
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    name = f"tester679_{uuid.uuid4().hex[:8]}"
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
    """Authenticated httpx.Client with session + CSRF pre-configured."""
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        res = bare.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session_cookie = res.cookies.get("session")
    csrf_token = res.cookies.get(CSRF_COOKIE_NAME)
    c = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield c
    c.close()


# ── AC1: _RaceCreateBody.priority rejects values outside {"A", "B", "C"} ─────

def test_ac1_create_invalid_priority_z_returns_422(authed):
    """AC1/AC4: POST /api/races with priority="Z" returns 422 naming priority (not 500)."""
    r = authed.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "name": "Bad Priority",
        "priority": "Z",
        "status": "planned",
    })
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "priority" in str(detail).lower(), f"Error must name 'priority': {detail}"


def test_ac1_create_invalid_priority_lowercase_returns_422(authed):
    """AC1: priority 'a' (lowercase) is outside the literal set and must return 422."""
    r = authed.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 10.0,
        "name": "Lowercase Priority",
        "priority": "a",
        "status": "planned",
    })
    assert r.status_code == 422, f"Expected 422 for priority='a', got {r.status_code}: {r.text}"


def test_ac1_create_invalid_priority_numeric_returns_422(authed):
    """AC1: priority '1' is outside the literal set and must return 422."""
    r = authed.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 10.0,
        "name": "Numeric Priority",
        "priority": "1",
        "status": "planned",
    })
    assert r.status_code == 422, f"Expected 422 for priority='1', got {r.status_code}: {r.text}"


# ── AC2: _RaceCreateBody.status rejects values outside the literal set ─────────

def test_ac2_create_invalid_status_returns_422(authed):
    """AC2/AC5: POST /api/races with status="invalid" returns 422 naming status (not 500)."""
    r = authed.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "name": "Bad Status",
        "priority": "A",
        "status": "invalid",
    })
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "status" in str(detail).lower(), f"Error must name 'status': {detail}"


def test_ac2_create_invalid_status_running_returns_422(authed):
    """AC2: status='running' is outside the literal set and must return 422."""
    r = authed.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 10.0,
        "name": "Running Status",
        "priority": "B",
        "status": "running",
    })
    assert r.status_code == 422, f"Expected 422 for status='running', got {r.status_code}: {r.text}"


# ── AC3: _RaceUpdateBody has same Literal constraints ─────────────────────────

def test_ac3_update_invalid_priority_returns_422(authed):
    """AC3/AC5: PATCH /api/races/{id} with priority="X" returns 422 naming priority."""
    r1 = authed.post("/api/races", json={
        "race_date": "2026-11-01",
        "distance_km": 10.0,
        "name": "Update Priority Test",
        "priority": "A",
        "status": "planned",
    })
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    try:
        r = authed.patch(f"/api/races/{race_id}", json={"priority": "X"})
        assert r.status_code == 422, f"Expected 422 for PATCH priority='X', got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "priority" in str(detail).lower(), f"Error must name 'priority': {detail}"
    finally:
        with _OrmSess(_engine) as db:
            race = db.get(_Race, uuid.UUID(race_id))
            if race:
                db.delete(race)
                db.commit()


def test_ac3_update_invalid_status_returns_422(authed):
    """AC3/AC5: PUT /api/races/{id} with status="running" returns 422 naming status."""
    r1 = authed.post("/api/races", json={
        "race_date": "2026-11-01",
        "distance_km": 10.0,
        "name": "Update Status Test",
        "priority": "B",
        "status": "planned",
    })
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    try:
        r = authed.put(f"/api/races/{race_id}", json={"status": "running"})
        assert r.status_code == 422, f"Expected 422 for PUT status='running', got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "status" in str(detail).lower(), f"Error must name 'status': {detail}"
    finally:
        with _OrmSess(_engine) as db:
            race = db.get(_Race, uuid.UUID(race_id))
            if race:
                db.delete(race)
                db.commit()


# ── AC6: Valid values continue to be accepted ─────────────────────────────────

@pytest.mark.parametrize("priority", ["A", "B", "C"])
def test_ac6_valid_priority_accepted(authed, priority):
    """AC6: All valid priority values ('A', 'B', 'C') are accepted and persisted."""
    r = authed.post("/api/races", json={
        "race_date": "2026-12-01",
        "distance_km": 10.0,
        "name": f"Valid Priority {priority}",
        "priority": priority,
        "status": "planned",
    })
    assert r.status_code == 201, f"Expected 201 for priority={priority!r}, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("priority") == priority, f"Expected priority={priority!r} in response, got {data.get('priority')!r}"

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


@pytest.mark.parametrize("status", ["planned", "done", "abandoned"])
def test_ac6_valid_status_accepted(authed, status):
    """AC6: All valid status values ('planned', 'done', 'abandoned') are accepted and persisted."""
    r = authed.post("/api/races", json={
        "race_date": "2026-12-01",
        "distance_km": 10.0,
        "name": f"Valid Status {status}",
        "priority": "B",
        "status": status,
    })
    assert r.status_code == 201, f"Expected 201 for status={status!r}, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("status") == status, f"Expected status={status!r} in response, got {data.get('status')!r}"

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac6_valid_priority_and_status_update(authed):
    """AC6: PUT /api/races/{id} with valid priority='C' and status='done' updates correctly."""
    r1 = authed.post("/api/races", json={
        "race_date": "2026-12-15",
        "distance_km": 42.195,
        "name": "Valid Update Test",
        "priority": "A",
        "status": "planned",
    })
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    try:
        r = authed.put(f"/api/races/{race_id}", json={"priority": "C", "status": "done"})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("priority") == "C", f"Expected priority='C', got {data.get('priority')!r}"
        assert data.get("status") == "done", f"Expected status='done', got {data.get('status')!r}"
    finally:
        with _OrmSess(_engine) as db:
            race = db.get(_Race, uuid.UUID(race_id))
            if race:
                db.delete(race)
                db.commit()


def test_ac6_null_priority_accepted(authed):
    """AC6: priority=None is still accepted (field is Optional)."""
    r = authed.post("/api/races", json={
        "race_date": "2026-12-01",
        "distance_km": 10.0,
        "name": "Null Priority Test",
        "priority": None,
        "status": "planned",
    })
    assert r.status_code == 201, f"Expected 201 for priority=None, got {r.status_code}: {r.text}"
    race_id = r.json()["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac6_null_status_accepted(authed):
    """AC6: status=None is still accepted (field is Optional)."""
    r = authed.post("/api/races", json={
        "race_date": "2026-12-01",
        "distance_km": 10.0,
        "name": "Null Status Test",
        "priority": "A",
        "status": None,
    })
    assert r.status_code == 201, f"Expected 201 for status=None, got {r.status_code}: {r.text}"
    race_id = r.json()["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()
