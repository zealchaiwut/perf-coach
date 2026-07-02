"""
Tests for issue #1153: Add daily bodyweight logging by date.

AC items tested:
(a) PUT /api/weight-entries/by-date creates a new entry for a given date
(b) PUT /api/weight-entries/by-date with same date upserts (updates, no duplicate)
(c) Weight is retrievable by date after submit (GET /api/weight-entries?from=d&to=d)
(d) weight.html has a date input field visible in the log form
(e) No weight field added to daily_metrics (model check)
(f) Migration for weight_entries is reversible (downgrade function exists)
(g) All modified Python files pass py_compile
"""
import uuid
import datetime
import py_compile
import os
import httpx
import pytest

from sqlalchemy.orm import Session as _OrmSession
from backend.db import engine
from backend.models import WeightEntry, DailyMetric
from backend.auth import hash_password
from backend.models import User as _User
from tests._admin_helpers import admin_cookies as _admin_cookies

_API_BASE = "http://127.0.0.1:9001"
_UPSERT_ENDPOINT = "/api/weight-entries/by-date"
_LIST_ENDPOINT = "/api/weight-entries"
_TEST_PW = "bwlog-test-pw-1153"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def http_client():
    with httpx.Client(base_url=_API_BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_user_id(http_client):
    name = f"bwlog_{uuid.uuid4().hex[:8]}"
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


def _put(client, entry_date, weight_kg, cookie, **kw):
    payload = {"entry_date": entry_date, "weight_kg": weight_kg}
    if "notes" in kw:
        payload["notes"] = kw["notes"]
    return client.put(_UPSERT_ENDPOINT, json=payload, cookies={"session": cookie})


# ── (a) PUT creates a new entry ───────────────────────────────────────────────

def test_a_put_creates_new_entry(http_client, test_user_id, session_cookie):
    """AC (a): PUT /api/weight-entries/by-date creates entry, returns 200 with row data."""
    date = "2025-01-10"
    res = _put(http_client, date, 75.5, session_cookie)
    assert res.status_code in (200, 201), res.text
    body = res.json()
    assert body["entry_date"] == date
    assert body["weight_kg"] == 75.5
    assert body["user_id"] == test_user_id


# ── (b) PUT same date upserts (updates, no duplicate) ─────────────────────────

def test_b_put_same_date_upserts(http_client, test_user_id, session_cookie):
    """AC (b): Submitting a weight for the same date twice upserts — updates, no duplicate."""
    date = "2025-01-11"

    # First submission
    r1 = _put(http_client, date, 75.5, session_cookie)
    assert r1.status_code in (200, 201), r1.text
    id1 = r1.json()["id"]

    # Second submission — must update, not duplicate
    r2 = _put(http_client, date, 76.0, session_cookie)
    assert r2.status_code in (200, 201), r2.text
    body2 = r2.json()
    assert body2["weight_kg"] == 76.0, "weight_kg should be updated to 76.0"

    # Verify only one entry for this date
    list_res = http_client.get(
        _LIST_ENDPOINT,
        params={"from": date, "to": date},
        cookies={"session": session_cookie},
    )
    assert list_res.status_code == 200, list_res.text
    entries = list_res.json()["entries"]
    assert len(entries) == 1, f"Expected 1 entry after upsert, got {len(entries)}"
    assert entries[0]["weight_kg"] == 76.0


# ── (c) Weight retrievable by date after submit ───────────────────────────────

def test_c_weight_retrievable_by_date(http_client, session_cookie):
    """AC (c): Weight value persists and is retrievable by date after submit."""
    date = "2025-01-12"
    _put(http_client, date, 74.2, session_cookie)

    list_res = http_client.get(
        _LIST_ENDPOINT,
        params={"from": date, "to": date},
        cookies={"session": session_cookie},
    )
    assert list_res.status_code == 200
    entries = list_res.json()["entries"]
    assert any(e["entry_date"] == date and e["weight_kg"] == 74.2 for e in entries)


# ── (d) Past date is saved independently ─────────────────────────────────────

def test_d_past_date_saved_independently(http_client, session_cookie):
    """AC/UAT5: Weight for a past date is saved independently of today's entry."""
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    _put(http_client, today, 75.0, session_cookie)
    _put(http_client, yesterday, 74.0, session_cookie)

    list_res = http_client.get(
        _LIST_ENDPOINT,
        params={"from": yesterday, "to": today},
        cookies={"session": session_cookie},
    )
    assert list_res.status_code == 200
    entries = list_res.json()["entries"]
    dates = {e["entry_date"] for e in entries}
    assert today in dates
    assert yesterday in dates

    today_entry = next(e for e in entries if e["entry_date"] == today)
    yesterday_entry = next(e for e in entries if e["entry_date"] == yesterday)
    assert today_entry["weight_kg"] == 75.0
    assert yesterday_entry["weight_kg"] == 74.0


# ── (e) No weight field on daily_metrics model ────────────────────────────────

def test_e_no_weight_on_daily_metrics():
    """AC (e): daily_metrics table/model has no weight column."""
    cols = [c.key for c in DailyMetric.__table__.columns]
    assert "weight_kg" not in cols, "weight_kg must not be on DailyMetric"
    assert "weight" not in cols, "weight must not be on DailyMetric"


# ── (f) weight_entries migration has a downgrade function ────────────────────

def test_f_migration_is_reversible():
    """AC (f): Migration for weight_entries defines a downgrade() function."""
    import importlib.util
    versions_dir = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions"
    )
    versions_dir = os.path.normpath(versions_dir)
    found = False
    for fname in os.listdir(versions_dir):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(versions_dir, fname)
        with open(path) as fh:
            src = fh.read()
        if "weight_entries" in src and "def downgrade" in src:
            found = True
            break
    assert found, "No migration file for weight_entries with a downgrade() function found"


# ── (g) weight.html has a date input in the entry form ───────────────────────

def test_g_weight_html_has_date_input():
    """AC/UAT1: weight.html contains a date input field in the log form."""
    html_path = os.path.join(
        os.path.dirname(__file__), "..", "frontend", "pages", "weight.html"
    )
    html_path = os.path.normpath(html_path)
    with open(html_path) as fh:
        content = fh.read()
    # Should have an <input type="date"> somewhere in the log section
    assert 'type="date"' in content or "type='date'" in content, (
        "weight.html must contain a date input field for the log form"
    )


# ── (h) PUT requires auth ─────────────────────────────────────────────────────

def test_h_put_requires_auth(http_client):
    """AC: PUT without session returns 401."""
    res = http_client.put(_UPSERT_ENDPOINT, json={"entry_date": "2025-01-15", "weight_kg": 75.0})
    assert res.status_code == 401, res.text


# ── (i) PUT validates weight range ────────────────────────────────────────────

def test_i_put_validates_weight_range(http_client, session_cookie):
    """AC: PUT returns 422 for weight_kg outside 20–300."""
    for bad in [5.0, 19.9, 300.1]:
        res = _put(http_client, "2025-01-16", bad, session_cookie)
        assert res.status_code == 422, f"Expected 422 for weight_kg={bad}, got {res.status_code}"


# ── (j) py_compile on modified Python files ──────────────────────────────────

def test_j_py_compile_passes():
    """AC (g): All modified Python files pass py_compile with no errors."""
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    files_to_check = [
        os.path.join(repo_root, "backend", "main.py"),
        os.path.join(repo_root, "backend", "models.py"),
    ]
    for fpath in files_to_check:
        try:
            py_compile.compile(fpath, doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"py_compile failed for {fpath}: {e}")
