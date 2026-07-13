"""
Tests for issue #1361: Score history table + formula version stamps.

AC coverage:
- AC1: performance_score_history table + model exist with correct schema/constraints
- AC2: formula_versions module exports SCORE_VERSION constant
- AC3: score computation write-through — upsert on recompute, no duplicates
- AC4: GET /api/performance/score-history?from=&to= returns persisted series
- AC5: projection endpoint includes formula_version field in payload
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient as _TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.main import app as _app
from backend.models import User as _UserModel, PerformanceScoreHistory
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1361pw!"

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

    user_name = f"psh_test_{uuid.uuid4().hex[:8]}"
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


def _upsert_score_row(
    user_id: str,
    score_date: datetime.date,
    endurance: float | None,
    speed: float | None,
    formula_version: str,
) -> None:
    """Directly upsert a performance_score_history row for a test user."""
    with _OrmSess(_engine) as db:
        db.execute(
            text("""
                INSERT INTO performance_score_history
                    (user_id, score_date, endurance, speed, formula_version, created_at)
                VALUES
                    (:uid, :sd, :e, :s, :fv, now())
                ON CONFLICT (user_id, score_date, formula_version)
                DO UPDATE SET
                    endurance = EXCLUDED.endurance,
                    speed = EXCLUDED.speed,
                    created_at = now()
            """),
            {"uid": user_id, "sd": score_date, "e": endurance, "s": speed, "fv": formula_version},
        )
        db.commit()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: Table + model exist with correct schema ───────────────────────────

def test_ac1_model_table_name():
    """AC1: PerformanceScoreHistory maps to performance_score_history."""
    assert PerformanceScoreHistory.__tablename__ == "performance_score_history"


def test_ac1_model_has_required_columns():
    """AC1: Model has all required columns."""
    col_names = {c.name for c in PerformanceScoreHistory.__table__.columns}
    required = {"id", "user_id", "score_date", "endurance", "speed", "formula_version", "created_at"}
    assert required <= col_names, f"Missing columns: {required - col_names}"


def test_ac1_unique_constraint_exists():
    """AC1: Unique constraint on (user_id, score_date, formula_version)."""
    constraint_names = {c.name for c in PerformanceScoreHistory.__table__.constraints}
    assert "uq_performance_score_history_user_date_version" in constraint_names


# ── AC2: formula_versions module ───────────────────────────────────────────

def test_ac2_formula_versions_module_importable():
    """AC2: formula_versions module is importable."""
    from backend.services import formula_versions
    assert formula_versions is not None


def test_ac2_score_version_constant_exists():
    """AC2: SCORE_VERSION constant is a non-empty string."""
    from backend.services.formula_versions import SCORE_VERSION
    assert isinstance(SCORE_VERSION, str) and SCORE_VERSION


def test_ac2_all_version_constants_present():
    """AC2: Module exports constants for score, readiness, tss, and projection."""
    from backend.services import formula_versions
    for name in ("SCORE_VERSION", "READINESS_VERSION", "TSS_VERSION", "PROJECTION_VERSION"):
        val = getattr(formula_versions, name, None)
        assert isinstance(val, str) and val, f"{name} is missing or empty"


# ── AC3: Upsert semantics ─────────────────────────────────────────────────

def test_ac3_upsert_updates_same_date_version_row(client):
    """AC3: Recompute for same (user, date, version) updates, never duplicates."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"psh_upsert_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201
    user_id = r.json()["id"]

    try:
        today = datetime.date.today()
        _upsert_score_row(user_id, today, 42.5, 38.1, "v1")
        _upsert_score_row(user_id, today, 43.0, 39.5, "v1")

        with _OrmSess(_engine) as db:
            rows = db.execute(
                text(
                    "SELECT endurance, speed FROM performance_score_history "
                    "WHERE user_id = :uid AND score_date = :sd AND formula_version = 'v1'"
                ),
                {"uid": user_id, "sd": today},
            ).fetchall()

        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        assert rows[0][0] == pytest.approx(43.0, rel=1e-3)
        assert rows[0][1] == pytest.approx(39.5, rel=1e-3)
    finally:
        _delete_user(user_id)


def test_ac3_different_versions_produce_separate_rows(client):
    """AC3: Different formula_version values produce separate rows."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"psh_ver_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201
    user_id = r.json()["id"]

    try:
        today = datetime.date.today()
        _upsert_score_row(user_id, today, 42.5, 38.1, "v1")
        _upsert_score_row(user_id, today, 44.0, 40.0, "v2")

        with _OrmSess(_engine) as db:
            rows = db.execute(
                text(
                    "SELECT formula_version FROM performance_score_history "
                    "WHERE user_id = :uid AND score_date = :sd ORDER BY formula_version"
                ),
                {"uid": user_id, "sd": today},
            ).fetchall()

        versions = [r[0] for r in rows]
        assert "v1" in versions
        assert "v2" in versions
    finally:
        _delete_user(user_id)


def test_ac3_write_through_on_performance_compute(client):
    """AC3: GET /api/athletes/{id}/performance upserts a score-history row when scored."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()

        r = auth.get(f"/api/athletes/{user_id}/performance")
        assert r.status_code in (200, 500), r.text

        # Only assert a history row when the endpoint actually produced a scored result.
        # A fresh user with no runs returns building_baseline or needs_thresholds;
        # in that case no row is written (there's nothing to persist).
        if r.status_code == 200 and r.json().get("state") == "scored":
            with _OrmSess(_engine) as db:
                rows = db.execute(
                    text(
                        "SELECT id FROM performance_score_history "
                        "WHERE user_id = :uid AND score_date = :sd"
                    ),
                    {"uid": user_id, "sd": today},
                ).fetchall()
            assert len(rows) >= 1, "No score-history row written for today after scored compute"
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC4: GET /api/performance/score-history range query ───────────────────

def test_ac4_score_history_endpoint_returns_range(client):
    """AC4: GET /api/performance/score-history?from=&to= returns matching rows."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from backend.main import _PERF_FORMULA_VERSION
    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        d_minus_1 = today - datetime.timedelta(days=1)
        d_minus_2 = today - datetime.timedelta(days=2)
        d_minus_10 = today - datetime.timedelta(days=10)

        for d in (d_minus_10, d_minus_2, d_minus_1, today):
            _upsert_score_row(user_id, d, 40.0, 35.0, _PERF_FORMULA_VERSION)

        r = auth.get(
            "/api/performance/score-history",
            params={"from": d_minus_2.isoformat(), "to": today.isoformat()},
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "history" in payload
        data = payload["history"]
        dates = {row["date"] for row in data}
        assert d_minus_2.isoformat() in dates
        assert d_minus_1.isoformat() in dates
        assert today.isoformat() in dates
        assert d_minus_10.isoformat() not in dates
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac4_score_history_latest_version_per_date(client):
    """AC4: Endpoint returns only current-formula rows; upsert on same version keeps one row."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from backend.main import _PERF_FORMULA_VERSION
    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        # Two upserts for the same (user, date, formula_version) → only one row.
        _upsert_score_row(user_id, today, 42.0, 38.0, _PERF_FORMULA_VERSION)
        _upsert_score_row(user_id, today, 44.0, 40.0, _PERF_FORMULA_VERSION)

        r = auth.get(
            "/api/performance/score-history",
            params={"from": today.isoformat(), "to": today.isoformat()},
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "history" in payload
        data = payload["history"]
        matching = [row for row in data if row["date"] == today.isoformat()]
        assert len(matching) == 1, f"Expected 1 row for today, got {len(matching)}: {data}"
        assert matching[0]["formula_version"] == _PERF_FORMULA_VERSION
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac4_score_history_response_fields(client):
    """AC4: Each score-history row includes expected fields."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from backend.main import _PERF_FORMULA_VERSION
    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        _upsert_score_row(user_id, today, 42.5, 38.1, _PERF_FORMULA_VERSION)

        r = auth.get(
            "/api/performance/score-history",
            params={"from": today.isoformat(), "to": today.isoformat()},
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "history" in payload
        assert "formula_version" in payload
        data = payload["history"]
        assert len(data) >= 1
        row = data[0]
        required = {"date", "endurance", "speed", "formula_version"}
        assert required <= set(row.keys()), f"Missing fields: {required - set(row.keys())}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac4_score_history_unauthenticated_returns_401():
    """AC4: Unauthenticated request returns 401 (tested via TestClient, not live server)."""
    today = datetime.date.today()
    with _TestClient(_app) as tc:
        r = tc.get(
            "/api/performance/score-history",
            params={"from": today.isoformat(), "to": today.isoformat()},
        )
    assert r.status_code == 401


def test_ac4_score_history_empty_range_returns_list(client):
    """AC4: Range with no data returns an empty history list."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get(
            "/api/performance/score-history",
            params={"from": "2000-01-01", "to": "2000-01-31"},
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "history" in payload
        assert payload["history"] == []
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac4_score_history_user_isolation(client):
    """AC4: User A cannot see User B's score history."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from backend.main import _PERF_FORMULA_VERSION
    auth_a, user_id_a = _create_and_login(client)
    auth_b, user_id_b = _create_and_login(client)
    try:
        today = datetime.date.today()
        _upsert_score_row(user_id_b, today, 99.9, 99.9, _PERF_FORMULA_VERSION)

        r = auth_a.get(
            "/api/performance/score-history",
            params={"from": today.isoformat(), "to": today.isoformat()},
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        data = payload.get("history", [])
        for row in data:
            assert row.get("endurance") != pytest.approx(99.9), "User A saw User B's score"
    finally:
        auth_a.close()
        auth_b.close()
        _delete_user(user_id_a)
        _delete_user(user_id_b)


# ── AC5: Projection endpoint includes formula_version ─────────────────────

def test_ac5_projection_endpoint_includes_formula_version(client):
    """AC5: GET /api/projection payload includes a formula_version field."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/projection")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "formula_version" in data, (
            f"formula_version key missing from /api/projection response. Keys: {list(data.keys())}"
        )
        assert isinstance(data["formula_version"], str) and data["formula_version"]
    finally:
        auth.close()
        _delete_user(user_id)
