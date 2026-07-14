"""Tests for issue #1484: POST /feel-entry route in worker API.

AC coverage:
- AC1: POST /feel-entry route exists in backend/worker_app.py
- AC2: Route requires valid Authorization: Bearer <token>; missing/wrong → 401
- AC3: feel_date is required; omitting → 400
- AC4: rpe_1_to_10, when provided, must be 1–10; out-of-range → 400
- AC5: notes must not exceed 10,000 chars when provided → 400
- AC6: At least one of rpe_1_to_10 or notes required; neither → 400
- AC7: Valid request inserts row into workout_feel and auto-links same-day workout
- AC8: Valid request with no same-day workout still succeeds (workout_id=null)
- AC9: Successful insert returns 201 with created record
- AC10: Webapp POST /api/feel is unchanged
- AC11: docs/worker.md documents the new route
"""
import os
import pathlib
import socket
import uuid
from datetime import date
from urllib.parse import urlparse

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.models import User as _UserModel, Workout, WorkoutFeel
from tests._admin_helpers import admin_cookies as _admin_cookies

WORKER_BASE_URL = os.environ.get("WORKER_BASE_URL") or "http://127.0.0.1:9100"
MAIN_BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1484pw!"
_TEST_TOKEN = "test-worker-api-token-1484"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _worker_reachable() -> bool:
    parsed = urlparse(WORKER_BASE_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9100
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _worker_reachable(),
    reason="worker server not reachable at " + WORKER_BASE_URL,
)


def _create_test_user() -> tuple[str, str]:
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    user_name = f"wfe_test_{uuid.uuid4().hex[:8]}"
    main_client = httpx.Client(base_url=MAIN_BASE_URL, timeout=10.0)
    try:
        r = main_client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]
    finally:
        main_client.close()
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()
    return user_id, user_name


def _create_workout(user_id: str, workout_date: date) -> str:
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    with _OrmSess(_engine) as db:
        row = Workout(
            user_id=uuid.UUID(user_id),
            workout_date=workout_date,
            name="Test workout",
            workout_type="run",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def _cleanup_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as db:
        db.query(WorkoutFeel).filter(WorkoutFeel.user_id == uuid.UUID(user_id)).delete()
        db.query(Workout).filter(Workout.user_id == uuid.UUID(user_id)).delete()
        db.commit()


@pytest.fixture
def worker_client():
    with httpx.Client(base_url=WORKER_BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(autouse=True)
def set_worker_token(monkeypatch):
    """Ensure WORKER_API_TOKEN is set for the worker process via env."""
    # The env var is read server-side; we pass the right token in the header.
    # This fixture just documents the required env var for the worker.
    pass


def _auth_header(token: str = _TEST_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── AC2: Auth ─────────────────────────────────────────────────────────────────

def test_1484__no_auth_header_returns_401(worker_client):
    """AC2: Missing Authorization header → 401."""
    r = worker_client.post("/feel-entry", json={"feel_date": "2026-07-14", "rpe_1_to_10": 7})
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"


def test_1484__wrong_token_returns_401(worker_client):
    """AC2: Wrong bearer token → 401."""
    r = worker_client.post(
        "/feel-entry",
        json={"feel_date": "2026-07-14", "rpe_1_to_10": 7},
        headers={"Authorization": "Bearer wrong-token-xyz"},
    )
    assert r.status_code == 401, f"expected 401 for wrong token, got {r.status_code}: {r.text}"


def test_1484__malformed_auth_header_returns_401(worker_client):
    """AC2: Malformed Authorization header (not Bearer scheme) → 401."""
    r = worker_client.post(
        "/feel-entry",
        json={"feel_date": "2026-07-14", "rpe_1_to_10": 7},
        headers={"Authorization": _TEST_TOKEN},  # missing "Bearer "
    )
    assert r.status_code == 401, f"expected 401 for malformed header, got {r.status_code}: {r.text}"


# ── AC3: feel_date required ───────────────────────────────────────────────────

def test_1484__missing_feel_date_returns_400(worker_client):
    """AC3: Omitting feel_date → 400 referencing feel_date."""
    user_id, user_name = _create_test_user()
    try:
        r = worker_client.post(
            "/feel-entry",
            json={"rpe_1_to_10": 7},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        body = r.json()
        assert "feel_date" in str(body).lower(), f"error should mention feel_date: {body}"
    finally:
        _cleanup_user(user_id)


# ── AC4: RPE validation ───────────────────────────────────────────────────────

def test_1484__rpe_zero_returns_400(worker_client):
    """AC4: rpe_1_to_10=0 (out of range) → 400."""
    user_id, user_name = _create_test_user()
    try:
        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": "2026-07-14", "rpe_1_to_10": 0},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 400, f"expected 400 for RPE=0, got {r.status_code}: {r.text}"
    finally:
        _cleanup_user(user_id)


def test_1484__rpe_eleven_returns_400(worker_client):
    """AC4: rpe_1_to_10=11 (out of range) → 400."""
    user_id, user_name = _create_test_user()
    try:
        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": "2026-07-14", "rpe_1_to_10": 11},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 400, f"expected 400 for RPE=11, got {r.status_code}: {r.text}"
    finally:
        _cleanup_user(user_id)


# ── AC5: notes length cap ─────────────────────────────────────────────────────

def test_1484__notes_too_long_returns_400(worker_client):
    """AC5: notes exceeding 10,000 chars → 400."""
    user_id, user_name = _create_test_user()
    try:
        long_notes = "x" * 10_001
        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": "2026-07-14", "notes": long_notes},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 400, f"expected 400 for long notes, got {r.status_code}: {r.text}"
    finally:
        _cleanup_user(user_id)


def test_1484__notes_exactly_10000_chars_accepted(worker_client):
    """AC5: notes of exactly 10,000 chars is valid."""
    user_id, user_name = _create_test_user()
    try:
        notes_10k = "y" * 10_000
        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": "2026-07-14", "notes": notes_10k},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 201, f"expected 201 for 10k notes, got {r.status_code}: {r.text}"
    finally:
        _cleanup_user(user_id)


# ── AC6: at least one field required ─────────────────────────────────────────

def test_1484__neither_rpe_nor_notes_returns_400(worker_client):
    """AC6: Supplying neither rpe_1_to_10 nor notes → 400."""
    user_id, user_name = _create_test_user()
    try:
        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": "2026-07-14"},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 400, f"expected 400 for neither field, got {r.status_code}: {r.text}"
    finally:
        _cleanup_user(user_id)


# ── AC7 + AC9: Valid request with same-day workout ────────────────────────────

def test_1484__valid_request_with_same_day_workout_returns_201_and_links(worker_client):
    """AC7+AC9: Valid request on date with same-day workout → 201, row inserted, workout linked."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    user_id, user_name = _create_test_user()
    try:
        feel_date = date(2026, 7, 10)
        workout_id = _create_workout(user_id, feel_date)

        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": feel_date.isoformat(), "rpe_1_to_10": 7, "notes": "Felt strong"},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        data = r.json()
        assert "id" in data, f"response missing id: {data}"

        # Verify row exists in DB with correct values and linked workout
        with _OrmSess(_engine) as db:
            row = db.query(WorkoutFeel).filter(
                WorkoutFeel.user_id == uuid.UUID(user_id),
                WorkoutFeel.feel_date == feel_date,
            ).first()
            assert row is not None, "no WorkoutFeel row found"
            assert row.rpe_1_to_10 == 7
            assert row.notes == "Felt strong"
            assert str(row.workout_id) == workout_id, f"workout_id mismatch: {row.workout_id} != {workout_id}"
    finally:
        _cleanup_user(user_id)


# ── AC8: No same-day workout ──────────────────────────────────────────────────

def test_1484__valid_request_no_same_day_workout_returns_201(worker_client):
    """AC8: Valid request with no same-day workout → 201, row inserted, workout_id null."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    user_id, user_name = _create_test_user()
    try:
        feel_date = date(2026, 7, 11)
        # No workout created for this date

        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": feel_date.isoformat(), "rpe_1_to_10": 5},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        data = r.json()
        assert "id" in data

        # Verify row exists with null workout_id
        with _OrmSess(_engine) as db:
            row = db.query(WorkoutFeel).filter(
                WorkoutFeel.user_id == uuid.UUID(user_id),
                WorkoutFeel.feel_date == feel_date,
            ).first()
            assert row is not None, "no WorkoutFeel row found"
            assert row.rpe_1_to_10 == 5
            assert row.workout_id is None, f"expected null workout_id, got {row.workout_id}"
    finally:
        _cleanup_user(user_id)


# ── AC9: Response shape ───────────────────────────────────────────────────────

def test_1484__response_contains_id_and_feel_date(worker_client):
    """AC9: Successful insert returns 201 with at least id in the body."""
    user_id, user_name = _create_test_user()
    try:
        feel_date = date(2026, 7, 12)
        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": feel_date.isoformat(), "notes": "Easy day"},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        data = r.json()
        assert "id" in data, f"response missing id field: {data}"
        assert "feel_date" in data, f"response missing feel_date field: {data}"
        assert data["feel_date"] == feel_date.isoformat()
    finally:
        _cleanup_user(user_id)


# ── AC10: Webapp POST /api/feel unchanged ─────────────────────────────────────

def test_1484__webapp_post_feel_still_works():
    """AC10: Webapp POST /api/feel still works as before (no regression)."""
    user_id, user_name = _create_test_user()
    try:
        client = httpx.Client(base_url=MAIN_BASE_URL, timeout=10.0)
        try:
            # Login
            r = client.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
            assert r.status_code == 200, f"login failed: {r.text}"

            # Post feel entry via webapp
            feel_date = date(2026, 7, 13)
            r = client.post(
                "/api/feel",
                json={"feel_date": feel_date.isoformat(), "rpe_1_to_10": 8},
            )
            assert r.status_code == 201, f"webapp POST /api/feel failed: {r.text}"
            data = r.json()
            assert "id" in data
            assert data["rpe_1_to_10"] == 8

            # Verify webapp still rejects missing feel_date with 422
            r = client.post("/api/feel", json={"rpe_1_to_10": 8})
            assert r.status_code == 422, f"expected 422 for missing feel_date from webapp, got {r.status_code}"
        finally:
            client.close()
    finally:
        _cleanup_user(user_id)


# ── AC11: docs/worker.md documents the route ─────────────────────────────────

def test_1484__worker_md_documents_feel_entry_route():
    """AC11: docs/worker.md contains documentation for POST /feel-entry."""
    docs_path = _root / "docs" / "worker.md"
    assert docs_path.exists(), "docs/worker.md not found"
    content = docs_path.read_text()
    assert "POST /feel-entry" in content, "docs/worker.md does not document POST /feel-entry"
    assert "WORKER_API_TOKEN" in content, "docs/worker.md does not mention WORKER_API_TOKEN"
    assert "Authorization" in content or "Bearer" in content, (
        "docs/worker.md does not document auth scheme"
    )
    assert "feel_date" in content, "docs/worker.md does not document feel_date field"
    assert "rpe_1_to_10" in content, "docs/worker.md does not document rpe_1_to_10 field"


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_1484__rpe_boundary_values_accepted(worker_client):
    """AC4: rpe values 1 and 10 (boundary) are accepted."""
    user_id, user_name = _create_test_user()
    try:
        for rpe, feel_day in [(1, date(2026, 7, 1)), (10, date(2026, 7, 2))]:
            r = worker_client.post(
                "/feel-entry",
                json={"feel_date": feel_day.isoformat(), "rpe_1_to_10": rpe},
                headers=_auth_header(),
                params={"user": user_name},
            )
            assert r.status_code == 201, f"expected 201 for rpe={rpe}, got {r.status_code}: {r.text}"
    finally:
        _cleanup_user(user_id)


def test_1484__notes_only_no_rpe_accepted(worker_client):
    """AC6: notes alone (no rpe) is valid."""
    user_id, user_name = _create_test_user()
    try:
        r = worker_client.post(
            "/feel-entry",
            json={"feel_date": "2026-07-14", "notes": "Just notes, no RPE"},
            headers=_auth_header(),
            params={"user": user_name},
        )
        assert r.status_code == 201, f"expected 201 for notes-only, got {r.status_code}: {r.text}"
    finally:
        _cleanup_user(user_id)
