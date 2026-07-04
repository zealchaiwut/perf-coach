"""Tests for issue #1210: Same-date weight upsert race condition fix.

AC items tested:
(1) Partial unique index exists on (user_id, entry_date) WHERE entry_time IS NULL
(2) PUT /api/weight-entries/by-date uses atomic INSERT...ON CONFLICT DO UPDATE
(3) Concurrent PUTs same date → exactly one row, no 5xx
(4) PUT for date with legacy timestamped row leaves at most one NULL-time row
(5) No 409-race fallback present in the by-date handler
"""
import uuid
import datetime
import threading
import httpx
import pytest

from sqlalchemy import text
from sqlalchemy.orm import Session as _OrmSession
from backend.db import engine
from backend.models import WeightEntry, User as _User
from backend.auth import hash_password
from tests._admin_helpers import admin_cookies as _admin_cookies

_API_BASE = "http://127.0.0.1:9001"
_UPSERT_URL = "/api/weight-entries/by-date"
_LIST_URL = "/api/weight-entries"
_TEST_PW = "pw-1210-test"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def http_client():
    with httpx.Client(base_url=_API_BASE, timeout=15) as c:
        yield c


@pytest.fixture(scope="module")
def test_user_id(http_client):
    name = f"race1210_{uuid.uuid4().hex[:8]}"
    res = http_client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    uid = res.json()["id"]
    pw_hash = hash_password(_TEST_PW)
    with _OrmSession(engine) as db:
        u = db.get(_User, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    http_client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def session_cookie(http_client, test_user_id):
    with _OrmSession(engine) as db:
        u = db.get(_User, uuid.UUID(test_user_id))
        name = u.name
    res = http_client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def csrf_token(http_client, session_cookie):
    """Fetch the CSRF token for authenticated mutation requests."""
    r = http_client.get("/api/csrf-token", cookies={"session": session_cookie})
    assert r.status_code == 200, f"CSRF fetch failed: {r.status_code} {r.text}"
    return r.json()["csrf_token"]


def _put(client, entry_date, weight_kg, session_cookie, csrf_token, notes=None):
    payload = {"entry_date": entry_date, "weight_kg": weight_kg}
    if notes is not None:
        payload["notes"] = notes
    return client.put(
        _UPSERT_URL,
        json=payload,
        cookies={"session": session_cookie, "csrf-token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )


def _count_null_time_rows(user_id: str, entry_date: str) -> int:
    uid = uuid.UUID(user_id)
    d = datetime.date.fromisoformat(entry_date)
    with _OrmSession(engine) as db:
        return (
            db.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date == d,
                WeightEntry.entry_time.is_(None),
            )
            .count()
        )


# ── AC1: Partial unique index exists in DB schema ─────────────────────────────

def test_ac1_partial_unique_index_exists():
    """AC1: Partial unique index on (user_id, entry_date) WHERE entry_time IS NULL exists."""
    with _OrmSession(engine) as db:
        result = db.execute(text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'weight_entries'
              AND indexdef ILIKE '%where%entry_time%null%'
        """)).fetchall()
    assert result, (
        "Expected a partial unique index on weight_entries "
        "WHERE entry_time IS NULL, but none was found."
    )
    with _OrmSession(engine) as db:
        result2 = db.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'weight_entries'
              AND indexdef ILIKE '%unique%'
              AND indexdef ILIKE '%where%entry_time%null%'
        """)).fetchall()
    assert result2, "The partial index must be UNIQUE."


# ── AC2: Handler uses atomic upsert (source code check) ───────────────────────

def test_ac2_handler_uses_on_conflict_do_update():
    """AC2: The by-date handler contains ON CONFLICT DO UPDATE, not a SELECT-then-INSERT."""
    import os
    main_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "backend", "main.py")
    )
    with open(main_path) as fh:
        src = fh.read()

    start = src.find("def upsert_weight_entry_by_date")
    assert start != -1, "upsert_weight_entry_by_date function not found"

    next_decorator = src.find("\n@app.", start + 1)
    handler_src = src[start:next_decorator] if next_decorator != -1 else src[start:]

    assert "on_conflict_do_update" in handler_src, (
        "Handler must use on_conflict_do_update for atomic upsert (AC2)"
    )
    assert "session.query" not in handler_src, (
        "Handler must not use SELECT-then-INSERT pattern (AC2)"
    )


# ── AC3: Concurrent PUTs produce exactly one row, no 5xx ─────────────────────

def test_ac3_concurrent_puts_same_date_one_row(http_client, test_user_id, session_cookie, csrf_token):
    """AC3: Two concurrent PUTs for the same date result in exactly one row, no 5xx."""
    entry_date = "2024-11-15"
    results = []

    def do_put(weight):
        with httpx.Client(base_url=_API_BASE, timeout=15) as c:
            r = c.put(
                _UPSERT_URL,
                json={"entry_date": entry_date, "weight_kg": weight},
                cookies={"session": session_cookie, "csrf-token": csrf_token},
                headers={"X-CSRF-Token": csrf_token},
            )
            results.append(r.status_code)

    t1 = threading.Thread(target=do_put, args=(70.1,))
    t2 = threading.Thread(target=do_put, args=(70.2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert all(s < 500 for s in results), f"Got 5xx responses: {results}"
    count = _count_null_time_rows(test_user_id, entry_date)
    assert count == 1, f"Expected exactly 1 NULL-time row after concurrent PUTs, got {count}"


# ── AC4: PUT with legacy timestamped row leaves at most one NULL-time row ──────

def test_ac4_legacy_row_no_duplicate_null_time(test_user_id, session_cookie, csrf_token, http_client):
    """AC4: PUT for date with legacy non-NULL entry_time leaves at most one NULL-time row."""
    entry_date_str = "2024-11-20"
    entry_date = datetime.date.fromisoformat(entry_date_str)
    uid = uuid.UUID(test_user_id)

    with _OrmSession(engine) as db:
        legacy = WeightEntry(
            user_id=uid,
            entry_date=entry_date,
            entry_time=datetime.time(7, 30),
            weight_kg=72.0,
            source="manual",
        )
        db.add(legacy)
        db.commit()

    r = _put(http_client, entry_date_str, 73.5, session_cookie, csrf_token)
    assert r.status_code < 500, f"Got {r.status_code}: {r.text}"
    assert r.status_code in (200, 201), f"Expected 2xx, got {r.status_code}: {r.text}"

    null_count = _count_null_time_rows(test_user_id, entry_date_str)
    assert null_count <= 1, (
        f"Expected at most 1 NULL-time row after PUT with legacy row, got {null_count}"
    )

    r2 = _put(http_client, entry_date_str, 74.0, session_cookie, csrf_token)
    assert r2.status_code < 500
    null_count2 = _count_null_time_rows(test_user_id, entry_date_str)
    assert null_count2 <= 1, (
        f"Expected at most 1 NULL-time row after second PUT, got {null_count2}"
    )


# ── AC5: No 409-race fallback in the by-date handler ─────────────────────────

def test_ac5_no_409_race_fallback():
    """AC5: The by-date handler must not contain a 409 race fallback."""
    import os
    main_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "backend", "main.py")
    )
    with open(main_path) as fh:
        src = fh.read()

    start = src.find("def upsert_weight_entry_by_date")
    assert start != -1
    next_decorator = src.find("\n@app.", start + 1)
    handler_src = src[start:next_decorator] if next_decorator != -1 else src[start:]

    assert "status_code=409" not in handler_src, (
        "Handler must not have a 409 race fallback — the DB constraint handles the race (AC5)"
    )


# ── Regression: basic upsert still works ──────────────────────────────────────

def test_regression_basic_upsert(http_client, test_user_id, session_cookie, csrf_token):
    """Regression: basic PUT creates and updates correctly."""
    entry_date = "2024-11-25"

    r1 = _put(http_client, entry_date, 68.0, session_cookie, csrf_token)
    assert r1.status_code in (200, 201), r1.text
    assert r1.json()["weight_kg"] == 68.0

    r2 = _put(http_client, entry_date, 69.5, session_cookie, csrf_token)
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["weight_kg"] == 69.5

    count = _count_null_time_rows(test_user_id, entry_date)
    assert count == 1, f"Expected 1 row after two PUTs, got {count}"
