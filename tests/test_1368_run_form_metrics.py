"""Tests for issue #1368: run_form_metrics table and endpoint.

AC coverage:
- AC1: New Alembic migration creates run_form_metrics with correct columns/unique constraint
- AC2: Extraction helper maps verified form_metrics keys; skips unparseable/absent payloads
- AC3: Rows upserted during sync (incremental write path wired into sync_runner)
- AC4: Backfill worker handler registered and callable
- AC5: GET /api/training/form-metrics returns per-run series + 28-day rolling means
- AC6: Upsert idempotency — writing the same stryd_activity_pk twice produces one row
- AC7: Skip-on-missing — activity with no form_metrics yields no row
- AC8: Endpoint range filter isolates the requested date window
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import (
    RunFormMetrics,
    StrydActivity,
    User as _UserModel,
)
from backend.services.form_metrics_extractor import extract_form_metrics_row
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1368pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


# ── helpers ──────────────────────────────────────────────────────────────────

def _create_and_login(client: httpx.Client) -> tuple[httpx.Client, str]:
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"fm_test_{uuid.uuid4().hex[:8]}"
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


def _make_stryd_activity(session: _OrmSess, user_id: str, *, form_metrics=None, start_time=None) -> StrydActivity:
    """Insert a minimal StrydActivity row, return the ORM object."""
    if start_time is None:
        start_time = datetime.datetime(2026, 1, 15, 7, 0, tzinfo=datetime.timezone.utc)
    ext_id = f"test_{uuid.uuid4().hex[:12]}"
    row = StrydActivity(
        user_id=uuid.UUID(user_id),
        stryd_activity_id=ext_id,
        start_time=start_time,
        name="Test run",
        raw_payload={"id": ext_id},
        form_metrics=form_metrics,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: Model / schema ──────────────────────────────────────────────────────

def test_ac1_model_tablename():
    """AC1: RunFormMetrics model importable and maps to correct table."""
    assert RunFormMetrics.__tablename__ == "run_form_metrics"


def test_ac1_required_columns():
    """AC1: run_form_metrics has all required columns."""
    col_names = {c.name for c in RunFormMetrics.__table__.columns}
    required = {
        "id", "user_id", "workout_id", "stryd_activity_pk",
        "run_date", "gct_ms", "lss_kn_m", "vertical_oscillation_cm",
        "cadence_spm", "power_w", "created_at",
    }
    assert required <= col_names, f"Missing columns: {required - col_names}"


def test_ac1_unique_constraint_on_stryd_activity_pk():
    """AC1: Unique constraint exists on stryd_activity_pk."""
    constraint_names = {c.name for c in RunFormMetrics.__table__.constraints}
    assert "uq_run_form_metrics_stryd_activity_pk" in constraint_names


# ── AC2: Extraction helper ────────────────────────────────────────────────────

_SAMPLE_FORM_METRICS = {
    "ground_contact_time_ms": 245.3,
    "leg_spring_stiffness": 9.8,
    "vertical_oscillation_cm": 7.1,
    "cadence_spm": 172.0,
}


def test_ac2_extraction_mapping():
    """AC2: Extraction helper maps verified form_metrics keys to row values."""
    result = extract_form_metrics_row(
        user_id="00000000-0000-0000-0000-000000000001",
        stryd_activity_pk="00000000-0000-0000-0000-000000000002",
        run_date=datetime.date(2026, 3, 1),
        form_metrics=_SAMPLE_FORM_METRICS,
        avg_power_w=285,
    )
    assert result is not None
    assert result["gct_ms"] == pytest.approx(245.3)
    assert result["lss_kn_m"] == pytest.approx(9.8)
    assert result["vertical_oscillation_cm"] == pytest.approx(7.1)
    assert result["cadence_spm"] == pytest.approx(172.0)
    assert result["power_w"] == pytest.approx(285.0)
    assert result["run_date"] == datetime.date(2026, 3, 1)


def test_ac2_partial_payload_still_returns_row():
    """AC2: Partial form_metrics (only some keys) still produces a row."""
    result = extract_form_metrics_row(
        user_id="00000000-0000-0000-0000-000000000001",
        stryd_activity_pk="00000000-0000-0000-0000-000000000002",
        run_date=datetime.date(2026, 3, 1),
        form_metrics={"cadence_spm": 168.0},
        avg_power_w=None,
    )
    assert result is not None
    assert result["cadence_spm"] == pytest.approx(168.0)
    assert result["gct_ms"] is None
    assert result["lss_kn_m"] is None


def test_ac2_skip_on_absent_payload():
    """AC2: Absent/empty form_metrics with no power -> row skipped (returns None)."""
    result = extract_form_metrics_row(
        user_id="00000000-0000-0000-0000-000000000001",
        stryd_activity_pk="00000000-0000-0000-0000-000000000002",
        run_date=datetime.date(2026, 3, 1),
        form_metrics=None,
        avg_power_w=None,
    )
    assert result is None


def test_ac2_skip_on_empty_dict():
    """AC2: Empty form_metrics dict with no power -> row skipped (returns None)."""
    result = extract_form_metrics_row(
        user_id="00000000-0000-0000-0000-000000000001",
        stryd_activity_pk="00000000-0000-0000-0000-000000000002",
        run_date=datetime.date(2026, 3, 1),
        form_metrics={},
        avg_power_w=None,
    )
    assert result is None


def test_ac2_unparseable_value_coerced_to_none():
    """AC2: Unparseable metric value treated as None, rest of row still written."""
    result = extract_form_metrics_row(
        user_id="00000000-0000-0000-0000-000000000001",
        stryd_activity_pk="00000000-0000-0000-0000-000000000002",
        run_date=datetime.date(2026, 3, 1),
        form_metrics={"cadence_spm": "bad_value", "ground_contact_time_ms": 230.0},
        avg_power_w=None,
    )
    assert result is not None
    assert result["cadence_spm"] is None
    assert result["gct_ms"] == pytest.approx(230.0)


# ── AC6: Upsert idempotency ───────────────────────────────────────────────────

def test_ac6_upsert_idempotency(client):
    """AC6: Writing the same stryd_activity_pk twice produces exactly one row."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    _, user_id = _create_and_login(client)
    try:
        from backend.services.run_form_metrics_service import upsert_form_metrics_for_activity

        with _OrmSess(_engine) as session:
            activity = _make_stryd_activity(
                session, user_id,
                form_metrics={"ground_contact_time_ms": 240.0, "cadence_spm": 174.0},
                start_time=datetime.datetime(2026, 3, 5, 6, 0, tzinfo=datetime.timezone.utc),
            )
            act_pk = activity.id

            # First upsert
            upsert_form_metrics_for_activity(session, activity)
            session.commit()

            # Second upsert (same activity, updated value)
            activity.avg_power_w = 300
            upsert_form_metrics_for_activity(session, activity)
            session.commit()

            count = session.execute(
                text("SELECT COUNT(*) FROM run_form_metrics WHERE stryd_activity_pk = :pk"),
                {"pk": str(act_pk)},
            ).scalar()
            assert count == 1, f"Expected 1 row, got {count}"

            # Updated value should be reflected
            row = session.execute(
                text("SELECT power_w FROM run_form_metrics WHERE stryd_activity_pk = :pk"),
                {"pk": str(act_pk)},
            ).fetchone()
            assert row is not None
            assert float(row[0]) == pytest.approx(300.0)
    finally:
        _delete_user(user_id)


# ── AC7: Skip-on-missing (DB level) ─────────────────────────────────────────

def test_ac7_skip_on_missing_no_row_inserted(client):
    """AC7: StrydActivity with no form_metrics and no power produces no row."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    _, user_id = _create_and_login(client)
    try:
        from backend.services.run_form_metrics_service import upsert_form_metrics_for_activity

        with _OrmSess(_engine) as session:
            activity = _make_stryd_activity(
                session, user_id,
                form_metrics=None,
            )
            act_pk = activity.id

            did_write = upsert_form_metrics_for_activity(session, activity)
            session.commit()

            assert did_write is False
            count = session.execute(
                text("SELECT COUNT(*) FROM run_form_metrics WHERE stryd_activity_pk = :pk"),
                {"pk": str(act_pk)},
            ).scalar()
            assert count == 0
    finally:
        _delete_user(user_id)


# ── AC5 + AC8: Endpoint ──────────────────────────────────────────────────────

def test_ac5_endpoint_returns_200_for_authenticated_user(client):
    """AC5: GET /api/training/form-metrics returns 200 for an authenticated user."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/form-metrics")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "runs" in data
        assert "rolling_means" in data
    finally:
        _delete_user(user_id)


def test_ac5_endpoint_returns_401_for_anonymous():
    """AC5: GET /api/training/form-metrics returns 401 for unauthenticated request."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as tc:
        r = tc.get("/api/training/form-metrics")
    assert r.status_code == 401


def test_ac5_endpoint_includes_rolling_means_keys(client):
    """AC5: rolling_means has expected metric keys."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        r = auth.get("/api/training/form-metrics")
        assert r.status_code == 200, r.text
        rm = r.json()["rolling_means"]
        for key in ("gct_ms", "lss_kn_m", "vertical_oscillation_cm", "cadence_spm", "power_w"):
            assert key in rm, f"Missing rolling_means key: {key}"
    finally:
        _delete_user(user_id)


def test_ac5_endpoint_series_populated_after_insert(client):
    """AC5: Endpoint returns the inserted run_form_metrics row in the runs list."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        from backend.services.run_form_metrics_service import upsert_form_metrics_for_activity

        run_date = datetime.date(2026, 3, 10)
        with _OrmSess(_engine) as session:
            activity = _make_stryd_activity(
                session, user_id,
                form_metrics={
                    "ground_contact_time_ms": 238.5,
                    "leg_spring_stiffness": 10.2,
                    "vertical_oscillation_cm": 6.8,
                    "cadence_spm": 176.0,
                },
                start_time=datetime.datetime(
                    run_date.year, run_date.month, run_date.day, 7, 0,
                    tzinfo=datetime.timezone.utc,
                ),
            )
            activity.avg_power_w = 290
            upsert_form_metrics_for_activity(session, activity)
            session.commit()

        r = auth.get(
            "/api/training/form-metrics",
            params={"from": "2026-03-01", "to": "2026-03-31"},
        )
        assert r.status_code == 200, r.text
        runs = r.json()["runs"]
        matching = [x for x in runs if x["run_date"] == run_date.isoformat()]
        assert len(matching) == 1
        m = matching[0]
        assert m["gct_ms"] == pytest.approx(238.5, abs=0.1)
        assert m["lss_kn_m"] == pytest.approx(10.2, abs=0.01)
        assert m["vertical_oscillation_cm"] == pytest.approx(6.8, abs=0.1)
        assert m["cadence_spm"] == pytest.approx(176.0, abs=0.1)
        assert m["power_w"] == pytest.approx(290.0, abs=0.1)
    finally:
        _delete_user(user_id)


def test_ac8_endpoint_range_filter(client):
    """AC8: Date range filter excludes runs outside the requested window."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    auth, user_id = _create_and_login(client)
    try:
        from backend.services.run_form_metrics_service import upsert_form_metrics_for_activity

        inside_date = datetime.date(2026, 4, 15)
        outside_date = datetime.date(2026, 3, 1)

        with _OrmSess(_engine) as session:
            for d in (inside_date, outside_date):
                activity = _make_stryd_activity(
                    session, user_id,
                    form_metrics={"cadence_spm": 170.0},
                    start_time=datetime.datetime(
                        d.year, d.month, d.day, 6, 0, tzinfo=datetime.timezone.utc
                    ),
                )
                upsert_form_metrics_for_activity(session, activity)
            session.commit()

        r = auth.get(
            "/api/training/form-metrics",
            params={"from": "2026-04-01", "to": "2026-04-30"},
        )
        assert r.status_code == 200, r.text
        dates = {row["run_date"] for row in r.json()["runs"]}
        assert inside_date.isoformat() in dates
        assert outside_date.isoformat() not in dates
    finally:
        _delete_user(user_id)


# ── AC4: Backfill handler registered ─────────────────────────────────────────

def test_ac4_backfill_handler_in_dispatch():
    """AC4: form_metrics_backfill handler is registered in worker _DISPATCH."""
    from backend.worker_app import _DISPATCH
    assert "form_metrics_backfill" in _DISPATCH


def test_ac3_incremental_hook_in_sync_runner():
    """AC3: sync_runner contains the incremental form_metrics upsert function."""
    from backend.services import sync_runner
    assert hasattr(sync_runner, "_upsert_form_metrics_incremental")
