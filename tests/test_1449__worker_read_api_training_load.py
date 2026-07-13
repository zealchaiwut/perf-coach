"""Tests for issue #1449: Worker read API 1/5 — GET /api/training/load

Tests the new read-only endpoint on the compute worker (port 9100)
that exposes CTL/ATL/TSB/ACWR + verdict for Hermes consumption.

AC coverage:
- AC1: Endpoint exists at GET /api/training/load in worker_app only
- AC2: date defaults to today (Bangkok TZ); user resolution with fallback chain
- AC3: CTL/ATL/TSB/ACWR from training_load_snapshots (latest ≤ date)
- AC4: Verdict from verdict_history; null if no row for date
- AC5: Response JSON shape correct with all fields
- AC6: No auth required (tailnet/localhost binding)
- AC7: Tests cover default date, explicit date, fallback to latest, null verdict, user-resolution failure
"""
import os
import pathlib
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import (
    TrainingLoadSnapshot,
    User as _UserModel,
    VerdictHistory,
)
from tests._admin_helpers import admin_cookies as _admin_cookies

WORKER_BASE_URL = os.environ.get("WORKER_BASE_URL") or "http://127.0.0.1:9100"
MAIN_BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1449pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


def _create_test_user() -> tuple[str, str]:
    """Create a test user in DB, return (user_id, username)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"wra_test_{uuid.uuid4().hex[:8]}"
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


def _upsert_snapshot(user_id: str, snap_date: date, ctl: float, atl: float, tsb: float, acwr: float | None) -> None:
    """Insert or update a training_load_snapshots row."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    with _OrmSess(_engine) as db:
        existing = (
            db.query(TrainingLoadSnapshot)
            .filter(
                TrainingLoadSnapshot.user_id == uuid.UUID(user_id),
                TrainingLoadSnapshot.snapshot_date == snap_date,
            )
            .first()
        )
        if existing:
            existing.ctl = ctl
            existing.atl = atl
            existing.tsb = tsb
            existing.acwr = acwr
            existing.tss_for_day = 0
        else:
            row = TrainingLoadSnapshot(
                user_id=uuid.UUID(user_id),
                snapshot_date=snap_date,
                ctl=ctl,
                atl=atl,
                tsb=tsb,
                acwr=acwr,
                tss_for_day=0,
            )
            db.add(row)
        db.commit()


def _upsert_verdict(user_id: str, verdict_date: date, verdict: str) -> None:
    """Insert or update a verdict_history row."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    with _OrmSess(_engine) as db:
        existing = (
            db.query(VerdictHistory)
            .filter(
                VerdictHistory.user_id == uuid.UUID(user_id),
                VerdictHistory.verdict_date == verdict_date,
            )
            .first()
        )
        if existing:
            existing.verdict = verdict
        else:
            row = VerdictHistory(
                user_id=uuid.UUID(user_id),
                verdict_date=verdict_date,
                verdict=verdict,
            )
            db.add(row)
        db.commit()


def _cleanup_user_data(user_id: str) -> None:
    """Clean up test data for a user."""
    if _engine is None:
        return

    with _OrmSess(_engine) as db:
        db.query(TrainingLoadSnapshot).filter(
            TrainingLoadSnapshot.user_id == uuid.UUID(user_id)
        ).delete()
        db.query(VerdictHistory).filter(
            VerdictHistory.user_id == uuid.UUID(user_id)
        ).delete()
        db.commit()


@pytest.fixture
def worker_client():
    """HTTP client for worker app."""
    with httpx.Client(base_url=WORKER_BASE_URL, timeout=10.0) as c:
        yield c


def test_1449__endpoint_exists_and_returns_200(worker_client):
    """AC1: Endpoint exists at GET /api/training/load in worker_app."""
    user_id, user_name = _create_test_user()
    try:
        # Set up a snapshot and verdict for today
        today = datetime.now(BANGKOK_TZ).date()
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)
        _upsert_verdict(user_id, today, "build")

        # Test endpoint is reachable and returns 200
        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, dict), f"expected dict, got {type(data)}"
    finally:
        _cleanup_user_data(user_id)


def test_1449__default_date_is_today_bangkok_tz(worker_client):
    """AC2: date defaults to today (Bangkok TZ, matching worker scheduling)."""
    user_id, user_name = _create_test_user()
    try:
        today = datetime.now(BANGKOK_TZ).date()
        tomorrow = today + timedelta(days=1)

        # Set up snapshots for today and tomorrow
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)
        _upsert_snapshot(user_id, tomorrow, ctl=51.0, atl=41.0, tsb=10.0, acwr=1.24)
        _upsert_verdict(user_id, today, "build")
        _upsert_verdict(user_id, tomorrow, "hold")

        # Omit ?date param — should return today's data
        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 200
        data = r.json()
        assert data["date"] == today.isoformat()
        assert data["ctl"] == 50.0
        assert data["verdict"] == "build"
    finally:
        _cleanup_user_data(user_id)


def test_1449__explicit_date_returns_that_date_snapshot(worker_client):
    """AC3: Explicit ?date returns that date's snapshot and verdict."""
    user_id, user_name = _create_test_user()
    try:
        # Set up snapshots for multiple dates
        target_date = date(2026, 7, 1)
        _upsert_snapshot(user_id, target_date, ctl=48.0, atl=39.0, tsb=9.0, acwr=1.23)
        _upsert_verdict(user_id, target_date, "back_off")

        # Fetch with explicit date
        r = worker_client.get(
            "/api/training/load",
            params={"user": user_name, "date": target_date.isoformat()},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["date"] == target_date.isoformat()
        assert data["ctl"] == 48.0
        assert data["atl"] == 39.0
        assert data["tsb"] == 9.0
        assert data["verdict"] == "back_off"
    finally:
        _cleanup_user_data(user_id)


def test_1449__fallback_to_latest_snapshot_when_date_has_none(worker_client):
    """AC3: If no snapshot for date, return latest snapshot ≤ date."""
    user_id, user_name = _create_test_user()
    try:
        # Set up snapshots with a gap
        date_with_snap = date(2026, 7, 1)
        date_without_snap = date(2026, 7, 5)

        _upsert_snapshot(user_id, date_with_snap, ctl=48.0, atl=39.0, tsb=9.0, acwr=1.23)
        _upsert_verdict(user_id, date_with_snap, "back_off")

        # Query for a future date with no snapshot — should return the latest one
        r = worker_client.get(
            "/api/training/load",
            params={"user": user_name, "date": date_without_snap.isoformat()},
        )
        assert r.status_code == 200
        data = r.json()
        # Should return the older snapshot
        assert data["snapshot_date"] == date_with_snap.isoformat()
        assert data["ctl"] == 48.0
        # Verdict for the query date (not found) should be null
        assert data["verdict"] is None
    finally:
        _cleanup_user_data(user_id)


def test_1449__null_verdict_when_no_verdict_row(worker_client):
    """AC4: verdict is null if no verdict_history row for the date."""
    user_id, user_name = _create_test_user()
    try:
        # Set up snapshot without verdict for same date
        today = datetime.now(BANGKOK_TZ).date()
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)
        # Don't create a verdict row

        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 200
        data = r.json()
        assert data["verdict"] is None
        assert data["verdict_date"] is None
    finally:
        _cleanup_user_data(user_id)


def test_1449__response_shape_has_all_required_fields(worker_client):
    """AC5: Response JSON has correct shape with all fields."""
    user_id, user_name = _create_test_user()
    try:
        today = datetime.now(BANGKOK_TZ).date()
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)
        _upsert_verdict(user_id, today, "build")

        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 200
        data = r.json()

        # Verify all required fields are present
        required_fields = {"date", "snapshot_date", "ctl", "atl", "tsb", "acwr", "verdict", "verdict_date"}
        assert set(data.keys()) == required_fields, f"missing or extra fields: {set(data.keys()) ^ required_fields}"

        # Verify types
        assert isinstance(data["date"], str)
        assert isinstance(data["snapshot_date"], str)
        assert isinstance(data["ctl"], float)
        assert isinstance(data["atl"], float)
        assert isinstance(data["tsb"], float)
        # acwr can be float or null
        assert data["acwr"] is None or isinstance(data["acwr"], float)
        # verdict can be string or null
        assert data["verdict"] is None or isinstance(data["verdict"], str)
        assert data["verdict_date"] is None or isinstance(data["verdict_date"], str)
    finally:
        _cleanup_user_data(user_id)


def test_1449__no_auth_required(worker_client):
    """AC6: No auth required — tailnet/localhost binding is the boundary."""
    user_id, user_name = _create_test_user()
    try:
        today = datetime.now(BANGKOK_TZ).date()
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)

        # Make request without any auth headers — should still work
        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 200, f"expected 200 without auth, got {r.status_code}"
    finally:
        _cleanup_user_data(user_id)


def test_1449__user_resolution_explicit_param(worker_client):
    """AC2: ?user=<username> resolves to that user."""
    user_id, user_name = _create_test_user()
    try:
        today = datetime.now(BANGKOK_TZ).date()
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)

        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 200
    finally:
        _cleanup_user_data(user_id)


def test_1449__user_resolution_failure_returns_400(worker_client):
    """AC2: User resolution failure (nonexistent user) returns 400."""
    nonexistent_user = f"nouser_{uuid.uuid4().hex[:8]}"
    r = worker_client.get("/api/training/load", params={"user": nonexistent_user})
    assert r.status_code == 400, f"expected 400 for missing user, got {r.status_code}: {r.text}"


def test_1449__invalid_date_format_returns_422(worker_client):
    """Invalid date format returns 422."""
    user_id, user_name = _create_test_user()
    try:
        today = datetime.now(BANGKOK_TZ).date()
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)

        r = worker_client.get(
            "/api/training/load",
            params={"user": user_name, "date": "2026-13-40"},  # invalid
        )
        assert r.status_code == 422, f"expected 422 for invalid date, got {r.status_code}"
    finally:
        _cleanup_user_data(user_id)


def test_1449__no_snapshots_returns_404(worker_client):
    """If user has no training_load_snapshots at all, return 404."""
    user_id, user_name = _create_test_user()
    try:
        # Don't create any snapshot for this user
        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 404, f"expected 404 for user with no snapshots, got {r.status_code}"
    finally:
        _cleanup_user_data(user_id)


def test_1449__acwr_nullable(worker_client):
    """ACWR can be null (when not enough history)."""
    user_id, user_name = _create_test_user()
    try:
        today = datetime.now(BANGKOK_TZ).date()
        # Create snapshot with acwr=None
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=None)

        r = worker_client.get("/api/training/load", params={"user": user_name})
        assert r.status_code == 200
        data = r.json()
        assert data["acwr"] is None
    finally:
        _cleanup_user_data(user_id)


def test_1449__verdict_values_valid(worker_client):
    """Verdict values are one of back_off/hold/build."""
    user_id, user_name = _create_test_user()
    try:
        today = datetime.now(BANGKOK_TZ).date()
        _upsert_snapshot(user_id, today, ctl=50.0, atl=40.0, tsb=10.0, acwr=1.25)

        for verdict_val in ["back_off", "hold", "build"]:
            _upsert_verdict(user_id, today, verdict_val)
            r = worker_client.get("/api/training/load", params={"user": user_name})
            assert r.status_code == 200
            data = r.json()
            assert data["verdict"] == verdict_val
    finally:
        _cleanup_user_data(user_id)
