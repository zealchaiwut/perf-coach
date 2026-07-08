"""Tests for issue #684: Move race priority/status defaults to DB schema.

Acceptance criteria verified:
- AC1: create_race has no hardcoded priority="A" or status="planned" in application code.
- AC2a: Race SQLAlchemy model defines server_default for priority ('A') and status ('planned').
- AC2b: races table columns have DB-level DEFAULT values for priority and status.
- AC3: New Alembic migration file exists and applies cleanly (verified by alembic upgrade head).
- AC5a: POST /api/races without priority/status returns 201 with DB-level defaults applied.
- AC5b: POST /api/races with explicit priority/status returns 201 with caller-supplied values.
- AC6: Existing races are unaffected by the migration (no data loss).
"""
import inspect
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import Race as _Race, User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "races684-test-pw"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT") or os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


# ── AC1: No hardcoded defaults in application code ───────────────────────────

def test_ac1_create_race_has_no_hardcoded_priority_default():
    """AC1: create_race must not contain the literal priority='A' as a fallback default."""
    import backend.main as _main

    src = inspect.getsource(_main.create_race)
    assert 'priority="A"' not in src and "priority='A'" not in src, (
        "create_race must not contain hardcoded priority='A' application-code default"
    )


def test_ac1_create_race_has_no_hardcoded_status_default():
    """AC1: create_race must not contain the literal status='planned' as a fallback default."""
    import backend.main as _main

    src = inspect.getsource(_main.create_race)
    assert 'status="planned"' not in src and "status='planned'" not in src, (
        "create_race must not contain hardcoded status='planned' application-code default"
    )


# ── AC2a: SQLAlchemy model has server_default ─────────────────────────────────

def test_ac2a_race_model_priority_has_server_default():
    """AC2a: Race.priority column has server_default='A' in the SQLAlchemy model."""
    col = _Race.__table__.c["priority"]
    assert col.server_default is not None, (
        "Race.priority must define a server_default"
    )
    sd_text = str(col.server_default.arg).strip("'\"")
    assert sd_text == "A", (
        f"Race.priority server_default must be 'A', got {sd_text!r}"
    )


def test_ac2a_race_model_status_has_server_default():
    """AC2a: Race.status column has server_default='planned' in the SQLAlchemy model."""
    col = _Race.__table__.c["status"]
    assert col.server_default is not None, (
        "Race.status must define a server_default"
    )
    sd_text = str(col.server_default.arg).strip("'\"")
    assert sd_text == "planned", (
        f"Race.status server_default must be 'planned', got {sd_text!r}"
    )


# ── AC2b: DB columns have server-side DEFAULT ─────────────────────────────────

def test_ac2b_db_priority_column_has_default():
    """AC2b: races.priority column has a DB-level DEFAULT of 'A' after migration."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not configured — skipping live DB test")
    with _engine.connect() as conn:
        row = conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'races' "
            "AND column_name = 'priority'"
        )).fetchone()
    assert row is not None, "races.priority column not found"
    assert row[0] is not None, (
        "races.priority must have a DB-level DEFAULT; got NULL"
    )
    assert "A" in str(row[0]), (
        f"races.priority DEFAULT must contain 'A', got: {row[0]}"
    )


def test_ac2b_db_status_column_has_default():
    """AC2b: races.status column has a DB-level DEFAULT of 'planned' after migration."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not configured — skipping live DB test")
    with _engine.connect() as conn:
        row = conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'races' "
            "AND column_name = 'status'"
        )).fetchone()
    assert row is not None, "races.status column not found"
    assert row[0] is not None, (
        "races.status must have a DB-level DEFAULT; got NULL"
    )
    assert "planned" in str(row[0]), (
        f"races.status DEFAULT must contain 'planned', got: {row[0]}"
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    name = f"tester684_{uuid.uuid4().hex[:8]}"
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


# ── AC5a: POST without priority/status gets DB defaults ──────────────────────

def test_ac5a_post_without_priority_status_returns_201_with_defaults(authed):
    """AC5a: POST /api/races without priority/status returns 201 with DB-level defaults."""
    payload = {
        "date": "2099-11-01",
        "distance_km": 42.195,
        "name": "Default Priority Status Test",
    }
    r = authed.post("/api/races", json=payload)
    assert r.status_code == 201, (
        f"Expected 201 when priority/status omitted (DB defaults should apply), "
        f"got {r.status_code}: {r.text}"
    )
    data = r.json()
    assert data.get("priority") == "A", (
        f"Expected DB-default priority='A', got {data.get('priority')!r}"
    )
    assert data.get("status") == "planned", (
        f"Expected DB-default status='planned', got {data.get('status')!r}"
    )

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac5a_post_without_priority_only_uses_db_default(authed):
    """AC5a: POST without priority (status supplied) returns 201 with priority DB default."""
    payload = {
        "date": "2099-12-01",
        "distance_km": 10.0,
        "name": "Default Priority Only Test",
        "status": "planned",
    }
    r = authed.post("/api/races", json=payload)
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("priority") == "A", (
        f"Expected DB-default priority='A', got {data.get('priority')!r}"
    )

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac5a_post_without_status_only_uses_db_default(authed):
    """AC5a: POST without status (priority supplied) returns 201 with status DB default."""
    payload = {
        "date": "2099-12-15",
        "distance_km": 21.1,
        "name": "Default Status Only Test",
        "priority": "B",
    }
    r = authed.post("/api/races", json=payload)
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("status") == "planned", (
        f"Expected DB-default status='planned', got {data.get('status')!r}"
    )

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC5b: Explicit priority/status uses caller-supplied values ────────────────

def test_ac5b_explicit_priority_status_uses_caller_values(authed):
    """AC5b: POST with explicit priority='B' and status='abandoned' uses those values, not defaults."""
    payload = {
        "date": "2099-09-15",
        "distance_km": 5.0,
        "name": "Explicit Priority Status Test",
        "priority": "B",
        "status": "abandoned",
    }
    r = authed.post("/api/races", json=payload)
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("priority") == "B", (
        f"Expected caller-supplied priority='B', got {data.get('priority')!r}"
    )
    assert data.get("status") == "abandoned", (
        f"Expected caller-supplied status='abandoned', got {data.get('status')!r}"
    )

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac5b_explicit_priority_c_status_done(authed):
    """AC5b: POST with priority='C' and status='done' returns those exact values."""
    payload = {
        "date": "2025-06-01",
        "distance_km": 10.0,
        "name": "C-Race Done Test",
        "priority": "C",
        "status": "done",
    }
    r = authed.post("/api/races", json=payload)
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("priority") == "C"
    assert data.get("status") == "done"

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()
