"""
Tests for issue #1353: Verdict history — persist daily verdict + inputs snapshot.

AC coverage:
- AC1: verdict_history table exists with correct schema
- AC2: upsert semantics — same-day recompute updates, never inserts duplicate
- AC3: GET /api/training/verdict-history?from=&to= returns series for session user
- AC4: user isolation — one user's history never leaks into another's
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel, VerdictHistory
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1353pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _create_and_login(client: httpx.Client) -> tuple[httpx.Client, str]:
    """Create a test user, set password, log in, return (auth_client, user_id)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"vh_test_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201, f"create user failed: {r.text}"
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r.status_code == 200, f"login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    auth = httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return auth, user_id


def _delete_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        u = sess.get(_UserModel, uuid.UUID(user_id))
        if u:
            sess.delete(u)
            sess.commit()


def _upsert_verdict_row(user_id: str, verdict_date: datetime.date, verdict: str, readiness: float | None = None) -> None:
    """Directly upsert a verdict_history row for a test user."""
    with _OrmSess(_engine) as db:
        db.execute(
            text("""
                INSERT INTO verdict_history (user_id, verdict_date, verdict, readiness, ctl, atl, tsb, acwr, created_at)
                VALUES (:uid, :vd, :v, :r, 30.0, 35.0, -5.0, 1.1, now())
                ON CONFLICT (user_id, verdict_date)
                DO UPDATE SET verdict = EXCLUDED.verdict, readiness = EXCLUDED.readiness,
                              created_at = now()
            """),
            {"uid": user_id, "vd": verdict_date, "v": verdict, "r": readiness},
        )
        db.commit()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: Table exists with correct schema ──────────────────────────────────

def test_ac1_verdict_history_table_and_model_exist():
    """AC1: VerdictHistory SQLAlchemy model maps to verdict_history table."""
    assert VerdictHistory.__tablename__ == "verdict_history"
    col_names = {c.name for c in VerdictHistory.__table__.columns}
    required = {"id", "user_id", "verdict_date", "verdict", "modifiers", "readiness", "ctl", "atl", "tsb", "acwr", "created_at"}
    assert required <= col_names, f"Missing columns: {required - col_names}"


def test_ac1_unique_constraint_per_user_date():
    """AC1: unique constraint exists on (user_id, verdict_date)."""
    constraints = {c.name for c in VerdictHistory.__table__.constraints}
    assert "uq_verdict_history_user_date" in constraints


# ── AC2: Upsert semantics ──────────────────────────────────────────────────

def test_ac2_upsert_updates_existing_row_same_date(client):
    """AC2: Second computation for the same day updates the row, not inserts."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    today = datetime.date.today()
    user_name = f"vh_upsert_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201
    user_id = r.json()["id"]

    try:
        # Insert first row
        _upsert_verdict_row(user_id, today, "build")

        # Verify only one row exists
        with _OrmSess(_engine) as db:
            rows = db.execute(
                text("SELECT verdict FROM verdict_history WHERE user_id = :uid AND verdict_date = :vd"),
                {"uid": user_id, "vd": today},
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "build"

        # Upsert with different verdict
        _upsert_verdict_row(user_id, today, "hold")

        # Still one row, updated verdict
        with _OrmSess(_engine) as db:
            rows = db.execute(
                text("SELECT verdict FROM verdict_history WHERE user_id = :uid AND verdict_date = :vd"),
                {"uid": user_id, "vd": today},
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "hold"
    finally:
        _delete_user(user_id)


def test_ac2_historical_dates_not_modified(client):
    """AC2: Writing today's verdict does not touch historical rows."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    user_name = f"vh_hist_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201
    user_id = r.json()["id"]

    try:
        # Write yesterday's row
        _upsert_verdict_row(user_id, yesterday, "back_off")

        # Write today's row
        _upsert_verdict_row(user_id, today, "build")

        # Yesterday's verdict must be unchanged
        with _OrmSess(_engine) as db:
            rows = db.execute(
                text("SELECT verdict FROM verdict_history WHERE user_id = :uid AND verdict_date = :vd"),
                {"uid": user_id, "vd": yesterday},
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "back_off"
    finally:
        _delete_user(user_id)


# ── AC3: GET /api/training/verdict-history range query ────────────────────

def test_ac3_verdict_history_endpoint_returns_range(client):
    """AC3: GET /api/training/verdict-history?from=&to= returns matching rows."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        d_minus_1 = today - datetime.timedelta(days=1)
        d_minus_2 = today - datetime.timedelta(days=2)
        d_minus_5 = today - datetime.timedelta(days=5)

        # Insert rows at d-2, d-1, today, and d-5 (outside query range)
        for d, v in [(d_minus_5, "build"), (d_minus_2, "hold"), (d_minus_1, "back_off"), (today, "build")]:
            _upsert_verdict_row(user_id, d, v)

        r = auth.get(
            "/api/training/verdict-history",
            params={"from": d_minus_2.isoformat(), "to": today.isoformat()},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        dates = [row["verdict_date"] for row in data]
        assert d_minus_2.isoformat() in dates
        assert d_minus_1.isoformat() in dates
        assert today.isoformat() in dates
        assert d_minus_5.isoformat() not in dates
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_verdict_history_endpoint_returns_correct_fields(client):
    """AC3: Each row in verdict-history contains expected fields."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        _upsert_verdict_row(user_id, today, "hold", readiness=72.5)

        r = auth.get(
            "/api/training/verdict-history",
            params={"from": today.isoformat(), "to": today.isoformat()},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data) == 1
        row = data[0]
        required_fields = {"verdict_date", "verdict", "ctl", "atl", "tsb", "acwr"}
        assert required_fields <= set(row.keys()), f"Missing: {required_fields - set(row.keys())}"
        assert row["verdict"] == "hold"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_unauthenticated_returns_401(client):
    """AC3: Unauthenticated request to verdict-history returns 401."""
    today = datetime.date.today()
    r = client.get(
        "/api/training/verdict-history",
        params={"from": today.isoformat(), "to": today.isoformat()},
    )
    assert r.status_code == 401


def test_ac3_empty_range_returns_empty_list(client):
    """AC3: Range with no data returns an empty list, not an error."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        far_past = datetime.date(2000, 1, 1)
        far_past_end = datetime.date(2000, 1, 31)
        r = auth.get(
            "/api/training/verdict-history",
            params={"from": far_past.isoformat(), "to": far_past_end.isoformat()},
        )
        assert r.status_code == 200, r.text
        assert r.json() == []
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC4: User isolation ────────────────────────────────────────────────────

def test_ac4_verdict_history_isolated_per_user(client):
    """AC4: User A cannot see User B's verdict history."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth_a, user_id_a = _create_and_login(client)
    auth_b, user_id_b = _create_and_login(client)
    try:
        today = datetime.date.today()
        # User B has a verdict row for today
        _upsert_verdict_row(user_id_b, today, "back_off")

        # User A queries the same range — should see no rows (they have none)
        r = auth_a.get(
            "/api/training/verdict-history",
            params={"from": today.isoformat(), "to": today.isoformat()},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # User A must see 0 rows (only user B has data)
        assert all(row.get("verdict") != "back_off" for row in data), \
            "User A saw user B's verdict"
    finally:
        auth_a.close()
        auth_b.close()
        _delete_user(user_id_a)
        _delete_user(user_id_b)


# ── AC2 (write-through): verdict compute writes to verdict_history today ──

def test_ac2_verdict_compute_writes_to_db_for_today(client):
    """AC2: Triggering a verdict computation for today persists to verdict_history."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()

        # Trigger a verdict via the weekly-summary endpoint (which calls _resolve_current_verdict)
        r = auth.get("/api/weekly-summary")
        # Accept 200 or 204 (may return 204 if no data yet)
        assert r.status_code in (200, 204), r.text

        # Check verdict_history for today
        with _OrmSess(_engine) as db:
            rows = db.execute(
                text("SELECT verdict FROM verdict_history WHERE user_id = :uid AND verdict_date = :vd"),
                {"uid": user_id, "vd": today},
            ).fetchall()

        # There should be exactly one row for today
        assert len(rows) == 1, f"Expected 1 verdict_history row, got {len(rows)}"
        assert rows[0][0] in ("build", "hold", "back_off")
    finally:
        auth.close()
        _delete_user(user_id)
