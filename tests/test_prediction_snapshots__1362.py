"""Tests for issue #1362: Prediction snapshots — persist projection forecasts.

Acceptance criteria verified:
- AC1: Alembic migration creates prediction_snapshots table (user_id, snapshot_date,
       payload JSONB, created_at, unique user+date).
- AC2: Snapshot written when projection is computed; throttled to once per day
       (first write wins; later same-day recomputes do NOT overwrite).
- AC3: Existing race_predictions / race_calibrations flow untouched.
- AC4: GET /api/projection/snapshots?from=&to= returns series for session user.
- AC5 (tests): once-per-day throttle, payload shape, isolation, calibration
       flow regression-untouched.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date, timedelta

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# ── DB-available flag ─────────────────────────────────────────────────────────
try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "snap1362pw!"

if _uat_url:
    from sqlalchemy import create_engine, text as _sql_text
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw, CSRF_COOKIE_NAME
    from backend.models import User as _UserModel, PredictionSnapshot as _PredSnap
    _db_engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _db_engine = None


def _skip_no_db():
    if _db_engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


# ─────────────────────────────────────────────────────────────────────────────
# AC1: Model + migration smoke tests (no DB required)
# ─────────────────────────────────────────────────────────────────────────────

def test_ac1_model_importable():
    """AC1: PredictionSnapshot model can be imported from backend.models."""
    from backend.models import PredictionSnapshot
    assert PredictionSnapshot.__tablename__ == "prediction_snapshots"


def test_ac1_model_has_required_columns():
    """AC1: PredictionSnapshot has user_id, snapshot_date, payload, created_at."""
    from backend.models import PredictionSnapshot
    cols = {c.name for c in PredictionSnapshot.__table__.columns}
    assert "user_id" in cols
    assert "snapshot_date" in cols
    assert "payload" in cols
    assert "created_at" in cols


def test_ac1_model_unique_constraint_on_user_date():
    """AC1: unique constraint exists on (user_id, snapshot_date)."""
    from backend.models import PredictionSnapshot
    uqs = {c.name for c in PredictionSnapshot.__table__.constraints
           if hasattr(c, 'name')}
    assert "uq_prediction_snapshots_user_date" in uqs


def test_ac1_migration_file_exists():
    """AC1: migration file for prediction_snapshots exists in alembic/versions/."""
    versions_dir = _ROOT / "alembic" / "versions"
    files = list(versions_dir.glob("*prediction_snapshots*.py"))
    assert files, "No migration file found for prediction_snapshots"


def test_ac1_migration_is_idempotent():
    """AC1: migration upgrade guards with table_exists check (idempotent)."""
    versions_dir = _ROOT / "alembic" / "versions"
    files = list(versions_dir.glob("*prediction_snapshots*.py"))
    assert files
    src = files[0].read_text()
    assert "table_exists" in src, "Migration must guard with table_exists for idempotency"


# ─────────────────────────────────────────────────────────────────────────────
# AC2 / AC5: maybe_write_prediction_snapshot — unit behaviour
# ─────────────────────────────────────────────────────────────────────────────

def test_ac5_snapshot_service_importable():
    """AC5: maybe_write_prediction_snapshot is importable."""
    from backend.services.prediction_snapshot import maybe_write_prediction_snapshot
    assert callable(maybe_write_prediction_snapshot)


def test_ac5_build_snapshot_payload_importable():
    """AC5: build_snapshot_payload helper is importable."""
    from backend.services.prediction_snapshot import build_snapshot_payload
    assert callable(build_snapshot_payload)


def test_ac5_payload_shape():
    """AC5: build_snapshot_payload returns required keys."""
    from backend.services.prediction_snapshot import build_snapshot_payload

    race_projections = [
        {
            "date": "2027-06-01",
            "name": "Half Marathon",
            "distance_km": 21.0975,
            "estimated_finish_seconds": 7200,
            "race_id": str(uuid.uuid4()),
        }
    ]
    ctl_series = [40.0, 41.0, 42.0]
    start_date = date(2026, 7, 13)
    races_meta = [{"id": race_projections[0]["race_id"], "date": "2027-06-01"}]

    payload = build_snapshot_payload(
        race_projections=race_projections,
        ctl_series=ctl_series,
        start_date=start_date,
        races_meta=races_meta,
        formula_version="1",
    )
    assert "races" in payload
    assert "peak_ctl" in payload
    assert "peak_week" in payload
    assert "formula_version" in payload
    assert payload["formula_version"] == "1"


def test_ac5_payload_races_include_race_id():
    """AC5: each race in payload has race_id and predicted_finish_seconds."""
    from backend.services.prediction_snapshot import build_snapshot_payload

    rid = str(uuid.uuid4())
    race_projections = [
        {
            "date": "2027-06-01",
            "name": "Marathon",
            "distance_km": 42.195,
            "estimated_finish_seconds": 14400,
            "race_id": rid,
        }
    ]
    payload = build_snapshot_payload(
        race_projections=race_projections,
        ctl_series=[50.0] * 30,
        start_date=date(2026, 7, 13),
        races_meta=[{"id": rid, "date": "2027-06-01"}],
        formula_version="1",
    )
    assert len(payload["races"]) == 1
    assert payload["races"][0]["race_id"] == rid
    assert payload["races"][0]["predicted_finish_seconds"] == 14400


def test_ac5_payload_peak_ctl_is_max_of_series():
    """AC5: peak_ctl equals the maximum value in ctl_series."""
    from backend.services.prediction_snapshot import build_snapshot_payload

    ctl_series = [30.0, 40.0, 55.0, 50.0, 45.0]
    payload = build_snapshot_payload(
        race_projections=[],
        ctl_series=ctl_series,
        start_date=date(2026, 7, 13),
        races_meta=[],
        formula_version="1",
    )
    assert payload["peak_ctl"] == 55.0


def test_ac5_payload_peak_week_is_iso_week_string():
    """AC5: peak_week is an ISO week string (YYYY-Www) for the week of peak CTL."""
    from backend.services.prediction_snapshot import build_snapshot_payload

    start_date = date(2026, 7, 13)
    ctl_series = [30.0, 55.0, 40.0]
    payload = build_snapshot_payload(
        race_projections=[],
        ctl_series=ctl_series,
        start_date=start_date,
        races_meta=[],
        formula_version="1",
    )
    # peak is at index 1 → start_date + 2 days
    peak_date = start_date + timedelta(days=2)
    year, week, _ = peak_date.isocalendar()
    expected = f"{year}-W{week:02d}"
    assert payload["peak_week"] == expected


# ─────────────────────────────────────────────────────────────────────────────
# AC2: once-per-day throttle (integration)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def snap_user_id():
    """Create a throwaway user for snapshot tests; yield user UUID; cleanup after."""
    _skip_no_db()
    import httpx
    from tests._admin_helpers import admin_cookies as _admin_cookies

    uname = f"snap1362_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname}, cookies=_admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = uuid.UUID(r.json()["id"])

    with _OrmSess(_db_engine) as db:
        u = db.get(_UserModel, user_id)
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    yield user_id

    with _OrmSess(_db_engine) as db:
        # cascade deletes prediction_snapshots via FK
        u = db.get(_UserModel, user_id)
        if u:
            db.delete(u)
            db.commit()


def test_ac2_first_write_persists(snap_user_id):
    """AC2: first call to maybe_write_prediction_snapshot creates a row."""
    _skip_no_db()
    from backend.services.prediction_snapshot import maybe_write_prediction_snapshot

    today = date.today()
    payload = {"races": [], "peak_ctl": 50.0, "peak_week": "2026-W29", "formula_version": "1"}

    # Clean slate
    with _OrmSess(_db_engine) as db:
        db.execute(
            _sql_text(
                "DELETE FROM prediction_snapshots WHERE user_id = :uid AND snapshot_date = :d"
            ),
            {"uid": snap_user_id, "d": today},
        )
        db.commit()

    maybe_write_prediction_snapshot(snap_user_id, today, payload)

    with _OrmSess(_db_engine) as db:
        row = (
            db.query(_PredSnap)
            .filter(_PredSnap.user_id == snap_user_id, _PredSnap.snapshot_date == today)
            .first()
        )
    assert row is not None
    assert row.payload["peak_ctl"] == 50.0


def test_ac2_second_write_same_day_does_not_overwrite(snap_user_id):
    """AC2: subsequent same-day call does NOT overwrite the first snapshot."""
    _skip_no_db()
    from backend.services.prediction_snapshot import maybe_write_prediction_snapshot

    today = date.today()
    first_payload = {"races": [], "peak_ctl": 50.0, "peak_week": "2026-W29", "formula_version": "1"}
    second_payload = {"races": [], "peak_ctl": 99.0, "peak_week": "2026-W30", "formula_version": "1"}

    # Ensure first write is there (previous test may have written it)
    maybe_write_prediction_snapshot(snap_user_id, today, first_payload)

    # Second write attempt
    maybe_write_prediction_snapshot(snap_user_id, today, second_payload)

    with _OrmSess(_db_engine) as db:
        row = (
            db.query(_PredSnap)
            .filter(_PredSnap.user_id == snap_user_id, _PredSnap.snapshot_date == today)
            .first()
        )
    assert row is not None
    assert row.payload["peak_ctl"] == 50.0, "Second write must NOT overwrite first snapshot"


def test_ac2_next_day_creates_new_row(snap_user_id):
    """AC2: write for a different date creates a new row."""
    _skip_no_db()
    from backend.services.prediction_snapshot import maybe_write_prediction_snapshot

    yesterday = date.today() - timedelta(days=1)
    payload = {"races": [], "peak_ctl": 42.0, "peak_week": "2026-W28", "formula_version": "1"}

    with _OrmSess(_db_engine) as db:
        db.execute(
            _sql_text(
                "DELETE FROM prediction_snapshots WHERE user_id = :uid AND snapshot_date = :d"
            ),
            {"uid": snap_user_id, "d": yesterday},
        )
        db.commit()

    maybe_write_prediction_snapshot(snap_user_id, yesterday, payload)

    with _OrmSess(_db_engine) as db:
        row = (
            db.query(_PredSnap)
            .filter(_PredSnap.user_id == snap_user_id, _PredSnap.snapshot_date == yesterday)
            .first()
        )
    assert row is not None
    assert row.payload["peak_ctl"] == 42.0


# ─────────────────────────────────────────────────────────────────────────────
# AC2: user isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_ac5_snapshot_isolation(snap_user_id):
    """AC5: snapshots are isolated per user — another user's writes don't appear."""
    _skip_no_db()
    from backend.services.prediction_snapshot import maybe_write_prediction_snapshot
    import httpx
    from tests._admin_helpers import admin_cookies as _admin_cookies

    uname2 = f"snap1362b_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname2}, cookies=_admin_cookies())
        assert r.status_code == 201
        user2_id = uuid.UUID(r.json()["id"])

    try:
        target_date = date(2020, 1, 1)
        maybe_write_prediction_snapshot(
            user2_id, target_date,
            {"races": [], "peak_ctl": 77.0, "peak_week": "2020-W01", "formula_version": "1"},
        )

        with _OrmSess(_db_engine) as db:
            rows = (
                db.query(_PredSnap)
                .filter(_PredSnap.user_id == snap_user_id, _PredSnap.snapshot_date == target_date)
                .all()
            )
        assert len(rows) == 0, "User 1 must not see User 2's snapshots"
    finally:
        with _OrmSess(_db_engine) as db:
            u2 = db.get(_UserModel, user2_id)
            if u2:
                db.delete(u2)
                db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# AC4: GET /api/projection/snapshots endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def snap_auth_client(snap_user_id):
    """Return an authenticated httpx Client for the snapshot test user."""
    _skip_no_db()
    import httpx

    with _OrmSess(_db_engine) as db:
        u = db.get(_UserModel, snap_user_id)
        uname = u.name

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    client = httpx.Client(
        base_url=BASE_URL, timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield client
    client.close()


def test_ac4_snapshots_endpoint_exists(snap_auth_client):
    """AC4: GET /api/projection/snapshots returns 200 for authenticated user."""
    r = snap_auth_client.get("/api/projection/snapshots")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


def test_ac4_snapshots_endpoint_returns_list(snap_auth_client):
    """AC4: response is a list."""
    r = snap_auth_client.get("/api/projection/snapshots")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_ac4_snapshots_endpoint_unauthenticated_returns_401():
    """AC4: unauthenticated request to /api/projection/snapshots returns 401."""
    _skip_no_db()
    import httpx
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.get("/api/projection/snapshots")
    assert r.status_code == 401


def test_ac4_snapshots_from_to_filters(snap_auth_client, snap_user_id):
    """AC4: from/to query params filter snapshots by date range."""
    _skip_no_db()
    from backend.services.prediction_snapshot import maybe_write_prediction_snapshot

    d1 = date(2021, 3, 1)
    d2 = date(2021, 3, 2)
    d3 = date(2021, 3, 3)

    with _OrmSess(_db_engine) as db:
        db.execute(
            _sql_text(
                "DELETE FROM prediction_snapshots WHERE user_id = :uid "
                "AND snapshot_date BETWEEN :a AND :b"
            ),
            {"uid": snap_user_id, "a": d1, "b": d3},
        )
        db.commit()

    for d in (d1, d2, d3):
        maybe_write_prediction_snapshot(
            snap_user_id, d,
            {"races": [], "peak_ctl": float(d.day), "peak_week": "2021-W09", "formula_version": "1"},
        )

    r = snap_auth_client.get("/api/projection/snapshots?from=2021-03-01&to=2021-03-02")
    assert r.status_code == 200
    body = r.json()
    dates = [row["snapshot_date"] for row in body]
    assert "2021-03-01" in dates
    assert "2021-03-02" in dates
    assert "2021-03-03" not in dates


def test_ac4_snapshot_response_shape(snap_auth_client, snap_user_id):
    """AC4: each returned item has snapshot_date and payload."""
    _skip_no_db()
    from backend.services.prediction_snapshot import maybe_write_prediction_snapshot

    d = date(2021, 4, 1)
    with _OrmSess(_db_engine) as db:
        db.execute(
            _sql_text(
                "DELETE FROM prediction_snapshots WHERE user_id = :uid AND snapshot_date = :d"
            ),
            {"uid": snap_user_id, "d": d},
        )
        db.commit()

    maybe_write_prediction_snapshot(
        snap_user_id, d,
        {"races": [], "peak_ctl": 60.0, "peak_week": "2021-W13", "formula_version": "1"},
    )
    r = snap_auth_client.get("/api/projection/snapshots?from=2021-04-01&to=2021-04-01")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    item = next((x for x in body if x["snapshot_date"] == "2021-04-01"), None)
    assert item is not None
    assert "payload" in item
    assert "snapshot_date" in item


# ─────────────────────────────────────────────────────────────────────────────
# AC3: calibration flow regression — race_predictions / race_calibrations untouched
# ─────────────────────────────────────────────────────────────────────────────

def test_ac3_race_predictions_model_unchanged():
    """AC3: RacePrediction model still has its original columns."""
    from backend.models import RacePrediction
    cols = {c.name for c in RacePrediction.__table__.columns}
    assert "race_id" in cols
    assert "prediction_date" in cols
    assert "predicted_seconds" in cols
    assert "band_seconds" in cols


def test_ac3_race_calibration_model_unchanged():
    """AC3: RaceCalibration model still has its original columns."""
    from backend.models import RaceCalibration
    cols = {c.name for c in RaceCalibration.__table__.columns}
    assert "race_id" in cols
    assert "race_date" in cols
    assert "predicted_seconds" in cols
    assert "actual_seconds" in cols
    assert "correction" in cols
    assert "source" in cols


def test_ac3_projection_module_unmodified_signature():
    """AC3: build_plan_projection_payload signature is not broken by this change."""
    from backend.services.projection import build_plan_projection_payload
    import inspect
    sig = inspect.signature(build_plan_projection_payload)
    # Original params must still be present
    for p in ("start_ctl", "start_atl", "start_date", "planned_load", "races", "thresholds"):
        assert p in sig.parameters, f"Parameter {p} missing from build_plan_projection_payload"
