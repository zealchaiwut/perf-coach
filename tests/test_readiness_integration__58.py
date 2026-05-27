"""
Integration tests for issue #58: daily_readiness table and compute job.

Tests cover:
  - daily_readiness table schema (columns, constraints, indexes)
  - Inserting a daily_metrics row and triggering the job writes a row to daily_readiness
  - components JSON is well-formed and its values sum to score
  - Idempotency: running the job twice does not create a duplicate row
  - Fallback: missing HRV history still produces a score
  - Null optional fields do not crash the job
"""
import json
import math
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from backend.db import engine
from services.readiness.job import compute_and_store

BASE_DATE = date(2099, 6, 1)   # far-future sentinel — avoids collisions


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_user_id():
    """Create a throw-away user for integration tests; delete on teardown."""
    name = f"readiness_test_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:name) RETURNING id"),
            {"name": name},
        ).fetchone()
        uid = str(row.id)
    yield uid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _insert_metric(conn, user_id: str, d: date, hrv=None, resting_hr=None, sleep_quality=None, energy=None):
    conn.execute(
        text(
            "INSERT INTO daily_metrics (user_id, metric_date, hrv, resting_hr, sleep_quality, energy) "
            "VALUES (:uid, :d, :hrv, :rhr, :sq, :en) "
            "ON CONFLICT (user_id, metric_date) DO NOTHING"
        ),
        {"uid": user_id, "d": str(d), "hrv": hrv, "rhr": resting_hr, "sq": sleep_quality, "en": energy},
    )


def _cleanup(conn, user_id: str):
    conn.execute(text("DELETE FROM daily_readiness WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM daily_metrics WHERE user_id = :uid"), {"uid": user_id})


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_daily_readiness_table_exists():
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'daily_readiness'"
        )).scalar()
    assert count == 1, "daily_readiness table not found — run alembic upgrade head"


def test_required_columns_exist():
    required = {"id", "user_id", "date", "score", "components", "computed_at", "daily_metric_id"}
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'daily_readiness'"
        )).fetchall()
    found = {r.column_name for r in rows}
    assert required <= found, f"Missing columns: {required - found}"


def test_unique_constraint_exists():
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' "
            "  AND table_name = 'daily_readiness' "
            "  AND constraint_type = 'UNIQUE' "
            "  AND constraint_name = 'uq_daily_readiness_user_date'"
        )).scalar()
    assert count == 1, "Unique constraint uq_daily_readiness_user_date not found"


def test_score_range_check_exists():
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' "
            "  AND table_name = 'daily_readiness' "
            "  AND constraint_type = 'CHECK' "
            "  AND constraint_name = 'ck_daily_readiness_score_range'"
        )).scalar()
    assert count == 1, "CHECK constraint ck_daily_readiness_score_range not found"


def test_index_exists():
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "  AND tablename = 'daily_readiness' "
            "  AND indexname = 'ix_daily_readiness_user_date'"
        )).scalar()
    assert count == 1, "Index ix_daily_readiness_user_date not found"


# ── Integration: job inserts a row ────────────────────────────────────────────

def test_job_inserts_row_with_plausible_score(test_user_id):
    """Insert 30 days of metrics + today, run job, assert row in daily_readiness."""
    target = BASE_DATE

    with engine.begin() as conn:
        _cleanup(conn, test_user_id)
        # Baseline: 30 preceding days
        for i in range(1, 31):
            _insert_metric(conn, test_user_id, target - timedelta(days=i),
                           hrv=60, resting_hr=55, sleep_quality=4, energy=4)
        # Today's metric
        _insert_metric(conn, test_user_id, target,
                       hrv=65, resting_hr=52, sleep_quality=4, energy=4)

    try:
        row = compute_and_store(test_user_id, target)
        assert row is not None
        assert 0.0 <= row["score"] <= 100.0
    finally:
        with engine.begin() as conn:
            _cleanup(conn, test_user_id)


def test_job_components_well_formed(test_user_id):
    """components JSON has all four keys and their sum equals the score."""
    target = BASE_DATE + timedelta(days=1)

    with engine.begin() as conn:
        _cleanup(conn, test_user_id)
        for i in range(1, 31):
            _insert_metric(conn, test_user_id, target - timedelta(days=i),
                           hrv=60, resting_hr=55, sleep_quality=3, energy=3)
        _insert_metric(conn, test_user_id, target,
                       hrv=65, resting_hr=52, sleep_quality=3, energy=3)

    try:
        row = compute_and_store(test_user_id, target)
        assert row is not None
        comp = row["components"]
        assert isinstance(comp, dict)
        for key in ("hrv_contribution", "rhr_contribution", "sleep_contribution", "energy_contribution"):
            assert key in comp, f"Missing key: {key}"
        total = sum(comp[k] for k in ("hrv_contribution", "rhr_contribution", "sleep_contribution", "energy_contribution"))
        assert math.isclose(total, row["score"], abs_tol=0.01), (
            f"Components sum {total} != score {row['score']}"
        )
    finally:
        with engine.begin() as conn:
            _cleanup(conn, test_user_id)


def test_job_idempotent_no_duplicate_row(test_user_id):
    """Running the job twice for the same (user_id, date) results in exactly one row."""
    target = BASE_DATE + timedelta(days=2)

    with engine.begin() as conn:
        _cleanup(conn, test_user_id)
        for i in range(1, 31):
            _insert_metric(conn, test_user_id, target - timedelta(days=i),
                           hrv=60, resting_hr=55, sleep_quality=4, energy=4)
        _insert_metric(conn, test_user_id, target,
                       hrv=65, resting_hr=52, sleep_quality=4, energy=4)

    try:
        r1 = compute_and_store(test_user_id, target)
        r2 = compute_and_store(test_user_id, target)
        assert r1 is not None and r2 is not None
        assert r1["score"] == r2["score"]

        with engine.connect() as conn:
            count = conn.execute(text(
                "SELECT COUNT(*) FROM daily_readiness WHERE user_id = :uid AND date = :d"
            ), {"uid": test_user_id, "d": str(target)}).scalar()
        assert count == 1, f"Expected 1 row after two runs, found {count}"
    finally:
        with engine.begin() as conn:
            _cleanup(conn, test_user_id)


def test_job_handles_insufficient_hrv_history(test_user_id):
    """With < HRV_MIN_DAYS HRV baseline rows, job still produces a score."""
    target = BASE_DATE + timedelta(days=3)

    with engine.begin() as conn:
        _cleanup(conn, test_user_id)
        # Only 1 preceding day with HRV (below HRV_MIN_DAYS=2)
        _insert_metric(conn, test_user_id, target - timedelta(days=1),
                       hrv=60, resting_hr=55, sleep_quality=3, energy=3)
        # Enough RHR baseline (no HRV in these rows)
        for i in range(2, 20):
            _insert_metric(conn, test_user_id, target - timedelta(days=i),
                           resting_hr=55, sleep_quality=3, energy=3)
        _insert_metric(conn, test_user_id, target,
                       hrv=65, resting_hr=52, sleep_quality=3, energy=3)

    try:
        row = compute_and_store(test_user_id, target)
        assert row is not None, "Job must not fail with insufficient HRV history"
        assert 0.0 <= row["score"] <= 100.0
        assert row["components"]["hrv_contribution"] == 0.0
    finally:
        with engine.begin() as conn:
            _cleanup(conn, test_user_id)


def test_job_handles_null_optional_fields(test_user_id):
    """All optional fields (sleep_quality, energy) null — job must not raise."""
    target = BASE_DATE + timedelta(days=4)

    with engine.begin() as conn:
        _cleanup(conn, test_user_id)
        for i in range(1, 31):
            _insert_metric(conn, test_user_id, target - timedelta(days=i),
                           hrv=60, resting_hr=55)
        _insert_metric(conn, test_user_id, target, hrv=65, resting_hr=52)

    try:
        row = compute_and_store(test_user_id, target)
        assert row is not None
        assert 0.0 <= row["score"] <= 100.0
        assert row["components"]["sleep_contribution"] == 0.0
        assert row["components"]["energy_contribution"] == 0.0
    finally:
        with engine.begin() as conn:
            _cleanup(conn, test_user_id)


def test_job_returns_none_when_no_metric_row(test_user_id):
    """If no daily_metrics row exists for the target date, job returns None."""
    target = BASE_DATE + timedelta(days=5)
    with engine.begin() as conn:
        _cleanup(conn, test_user_id)

    result = compute_and_store(test_user_id, target)
    assert result is None
