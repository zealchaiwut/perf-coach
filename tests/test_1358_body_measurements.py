"""
Tests for issue #1358: Body measurements — waist and body-fat logging.

AC coverage:
- AC1: body_measurements table exists (model + schema)
- AC2: CRUD + upsert endpoints (POST upsert-by-date, GET range, PATCH, DELETE)
- AC3: Validation — waist 40-200 cm, body-fat 3-60%, at least one field required
- AC4: Range query with from/to filters
- AC5: User isolation — one user's data never leaks to another
- AC6: Export endpoint GET /api/exports/body-measurements returns CSV
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
from backend.models import User as _UserModel, BodyMeasurement
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1358pw!"

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
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"bm_test_{uuid.uuid4().hex[:8]}"
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


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: Table exists with correct schema ─────────────────────────────────────

def test_ac1_model_importable_and_correct_tablename():
    """AC1: BodyMeasurement model importable, maps to body_measurements."""
    assert BodyMeasurement.__tablename__ == "body_measurements"


def test_ac1_required_columns_present():
    """AC1: body_measurements has all required columns."""
    col_names = {c.name for c in BodyMeasurement.__table__.columns}
    required = {"id", "user_id", "measure_date", "waist_cm", "body_fat_pct", "source", "notes", "created_at"}
    assert required <= col_names, f"Missing: {required - col_names}"


def test_ac1_unique_constraint_user_date():
    """AC1: Unique constraint exists on (user_id, measure_date)."""
    constraint_names = {c.name for c in BodyMeasurement.__table__.constraints}
    assert "uq_body_measurements_user_date" in constraint_names


# ── AC2: CRUD + upsert ────────────────────────────────────────────────────────

def test_ac2_post_creates_measurement(client):
    """AC2: POST /api/body-measurements with waist upserts and returns the row."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 88.5})
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert float(data["waist_cm"]) == pytest.approx(88.5, abs=0.01)
        assert data["measure_date"] == today
        assert "id" in data
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac2_post_upserts_on_same_date(client):
    """AC2: Second POST for the same date updates rather than inserts duplicate."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r1 = auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 88.5})
        assert r1.status_code in (200, 201)

        r2 = auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 87.0})
        assert r2.status_code in (200, 201)

        # Same id (upsert) or different id but only one row in DB
        with _OrmSess(_engine) as db:
            count = db.execute(
                text("SELECT COUNT(*) FROM body_measurements WHERE user_id = :uid AND measure_date = :d"),
                {"uid": user_id, "d": today},
            ).scalar()
        assert count == 1, f"Expected 1 row after upsert, got {count}"
        assert float(r2.json()["waist_cm"]) == pytest.approx(87.0, abs=0.01)
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac2_get_range_returns_entries(client):
    """AC2: GET /api/body-measurements?from=&to= returns created entries."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        yesterday = (today - datetime.timedelta(days=1)).isoformat()
        today_str = today.isoformat()

        auth.post("/api/body-measurements", json={"measure_date": yesterday, "waist_cm": 89.0})
        auth.post("/api/body-measurements", json={"measure_date": today_str, "waist_cm": 88.5})

        r = auth.get("/api/body-measurements", params={"from": yesterday, "to": today_str})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "measurements" in data
        assert len(data["measurements"]) == 2
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac2_patch_updates_measurement(client):
    """AC2: PATCH /api/body-measurements/{id} updates the specified fields."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 88.5})
        assert r.status_code in (200, 201)
        meas_id = r.json()["id"]

        r2 = auth.patch(f"/api/body-measurements/{meas_id}", json={"waist_cm": 87.0, "body_fat_pct": 18.5})
        assert r2.status_code == 200, r2.text
        assert float(r2.json()["waist_cm"]) == pytest.approx(87.0, abs=0.01)
        assert float(r2.json()["body_fat_pct"]) == pytest.approx(18.5, abs=0.01)
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac2_delete_removes_measurement(client):
    """AC2: DELETE /api/body-measurements/{id} removes the row."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 88.5})
        assert r.status_code in (200, 201)
        meas_id = r.json()["id"]

        r2 = auth.delete(f"/api/body-measurements/{meas_id}")
        assert r2.status_code == 200, r2.text
        assert r2.json().get("deleted") is True

        # Verify gone
        with _OrmSess(_engine) as db:
            count = db.execute(
                text("SELECT COUNT(*) FROM body_measurements WHERE id = :mid"),
                {"mid": meas_id},
            ).scalar()
        assert count == 0
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC3: Validation ────────────────────────────────────────────────────────────

def test_ac3_neither_field_returns_422(client):
    """AC3: POST with neither waist_cm nor body_fat_pct returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today})
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_waist_below_40_returns_422(client):
    """AC3: waist_cm below 40 returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 30.0})
        assert r.status_code == 422, r.text
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_waist_above_200_returns_422(client):
    """AC3: waist_cm above 200 returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 210.0})
        assert r.status_code == 422, r.text
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_body_fat_below_3_returns_422(client):
    """AC3: body_fat_pct below 3 returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "body_fat_pct": 1.0})
        assert r.status_code == 422, r.text
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_body_fat_above_60_returns_422(client):
    """AC3: body_fat_pct above 60 returns 422."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "body_fat_pct": 65.0})
        assert r.status_code == 422, r.text
    finally:
        auth.close()
        _delete_user(user_id)


def test_ac3_body_fat_only_is_valid(client):
    """AC3: body_fat_pct alone (without waist_cm) is accepted."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth.post("/api/body-measurements", json={"measure_date": today, "body_fat_pct": 18.5})
        assert r.status_code in (200, 201), r.text
        assert float(r.json()["body_fat_pct"]) == pytest.approx(18.5, abs=0.01)
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC4: Range query ──────────────────────────────────────────────────────────

def test_ac4_range_filters_by_date(client):
    """AC4: GET with from/to only returns entries within that range."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today()
        d1 = (today - datetime.timedelta(days=14)).isoformat()
        d2 = (today - datetime.timedelta(days=7)).isoformat()
        d3 = today.isoformat()

        auth.post("/api/body-measurements", json={"measure_date": d1, "waist_cm": 91.0})
        auth.post("/api/body-measurements", json={"measure_date": d2, "waist_cm": 90.0})
        auth.post("/api/body-measurements", json={"measure_date": d3, "waist_cm": 89.0})

        r = auth.get("/api/body-measurements", params={"from": d1, "to": d2})
        assert r.status_code == 200
        dates = {m["measure_date"] for m in r.json()["measurements"]}
        assert d1 in dates and d2 in dates and d3 not in dates
    finally:
        auth.close()
        _delete_user(user_id)


# ── AC5: User isolation ────────────────────────────────────────────────────────

def test_ac5_user_isolation(client):
    """AC5: User A cannot see User B's body measurements."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth_a, uid_a = _create_and_login(client)
    auth_b, uid_b = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        r = auth_a.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 88.5})
        assert r.status_code in (200, 201)

        # User B queries same date range
        r_b = auth_b.get("/api/body-measurements", params={"from": today, "to": today})
        assert r_b.status_code == 200
        assert len(r_b.json()["measurements"]) == 0, "User B should not see User A's data"
    finally:
        auth_a.close()
        auth_b.close()
        _delete_user(uid_a)
        _delete_user(uid_b)


# ── AC6: Export endpoint ──────────────────────────────────────────────────────

def test_ac6_export_csv_returns_csv(client):
    """AC6: GET /api/exports/body-measurements returns CSV with correct headers."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        today = datetime.date.today().isoformat()
        auth.post("/api/body-measurements", json={"measure_date": today, "waist_cm": 88.5, "body_fat_pct": 18.0})

        r = auth.get("/api/exports/body-measurements")
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "text/csv" in ct or "csv" in ct.lower()
        text_body = r.text
        assert "measure_date" in text_body
        assert "waist_cm" in text_body
        assert "88.5" in text_body
    finally:
        auth.close()
        _delete_user(user_id)
