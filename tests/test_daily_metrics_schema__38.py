"""
Tests for issue #38: Create daily_metrics table for rhr, hrv, sleep, energy, mood.
Verifies schema, constraints, seed data, trigger, and cascade delete via direct DB
connection (no HTTP API endpoints exist for daily_metrics on this feature branch).
"""
import uuid
import time
import pytest
from datetime import date, timedelta
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine

BASE_DATE = date(2099, 1, 1)   # far-future sentinel — avoids collisions with seed rows


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def alice_id():
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM users WHERE name = 'Alice'")).fetchone()
    assert row is not None, "Alice not found — seed not run?"
    return str(row.id)


# ── AC / Step 1: table, columns, constraints, and index exist ─────────────────

def test_table_exists():
    """daily_metrics table is present in the public schema."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'daily_metrics'"
        )).scalar()
    assert count == 1, "daily_metrics table not found — was alembic upgrade head run?"


def test_all_required_columns_exist():
    """All 12 columns from the spec exist with the correct nullable settings."""
    required = {
        "id":            False,  # NOT NULL
        "user_id":       False,
        "metric_date":   False,
        "resting_hr":    True,
        "hrv":           True,
        "sleep_hours":   True,
        "sleep_quality": True,
        "energy":        True,
        "mood":          True,
        "notes":         True,
        "created_at":    True,
        "updated_at":    True,
    }
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'daily_metrics'"
        )).fetchall()
    found = {r.column_name: (r.is_nullable == "YES") for r in rows}
    for col, nullable in required.items():
        assert col in found, f"Column '{col}' is missing from daily_metrics"
        assert found[col] == nullable, (
            f"Column '{col}' nullable={found[col]} but expected nullable={nullable}"
        )


def test_unique_constraint_exists():
    """Unique constraint uq_daily_metrics_user_date exists on (user_id, metric_date)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' "
            "  AND table_name = 'daily_metrics' "
            "  AND constraint_type = 'UNIQUE' "
            "  AND constraint_name = 'uq_daily_metrics_user_date'"
        )).scalar()
    assert count == 1, "Unique constraint 'uq_daily_metrics_user_date' not found"


def test_index_exists():
    """Index ix_daily_metrics_user_date exists for time-series queries."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "  AND tablename = 'daily_metrics' "
            "  AND indexname = 'ix_daily_metrics_user_date'"
        )).scalar()
    assert count == 1, "Index 'ix_daily_metrics_user_date' not found"


def test_trigger_exists():
    """trg_daily_metrics_updated_at trigger exists (keeps updated_at current on UPDATE)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.triggers "
            "WHERE trigger_schema = 'public' "
            "  AND event_object_table = 'daily_metrics' "
            "  AND trigger_name = 'trg_daily_metrics_updated_at'"
        )).scalar()
    assert count == 1, "Trigger 'trg_daily_metrics_updated_at' not found"


def test_fk_to_users_exists():
    """FK from daily_metrics.user_id → users.id exists."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
            "JOIN information_schema.table_constraints tc "
            "  ON rc.constraint_name = tc.constraint_name "
            " AND tc.table_schema = 'public' "
            " AND tc.table_name = 'daily_metrics'"
        )).scalar()
    assert count >= 1, "No FK from daily_metrics to users found"


# ── AC / Step 2: seed data ────────────────────────────────────────────────────

def test_alice_has_14_daily_metrics_rows(alice_id):
    """Alice has exactly 14 daily_metrics rows after seed.py is run."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM daily_metrics WHERE user_id = :uid"
        ), {"uid": alice_id}).scalar()
    assert count >= 14, (
        f"Expected ≥14 daily_metrics rows for Alice, found {count}. "
        "Run `python backend/seed.py` on UAT to populate seed data."
    )


def test_seed_rows_have_realistic_resting_hr(alice_id):
    """Seeded resting_hr values are in the realistic range 50–60."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT resting_hr FROM daily_metrics "
            "WHERE user_id = :uid AND resting_hr IS NOT NULL "
            "ORDER BY metric_date DESC LIMIT 14"
        ), {"uid": alice_id}).fetchall()
    assert rows, "No non-null resting_hr rows found for Alice"
    for row in rows:
        assert 20 <= row.resting_hr <= 200, f"resting_hr {row.resting_hr} outside valid range"


def test_seed_rows_have_realistic_hrv(alice_id):
    """Seeded hrv values are in the realistic range 40–80."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT hrv FROM daily_metrics "
            "WHERE user_id = :uid AND hrv IS NOT NULL "
            "ORDER BY metric_date DESC LIMIT 14"
        ), {"uid": alice_id}).fetchall()
    assert rows, "No non-null hrv rows found for Alice"
    for row in rows:
        assert 0 <= row.hrv <= 300, f"hrv {row.hrv} outside valid range"


def test_seed_rows_cover_14_distinct_dates(alice_id):
    """Seed inserts exactly 14 rows on 14 distinct dates."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(DISTINCT metric_date) FROM daily_metrics WHERE user_id = :uid"
        ), {"uid": alice_id}).scalar()
    assert count >= 14, f"Expected ≥14 distinct metric_dates for Alice, found {count}"


# ── AC / Step 3: resting_hr CHECK constraint ──────────────────────────────────

def test_resting_hr_below_20_rejected(alice_id):
    """INSERT with resting_hr=10 violates CHECK (must be 20–200) — IntegrityError raised."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_resting_hr|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
                "VALUES (:uid, :d, 10)"
            ), {"uid": alice_id, "d": str(BASE_DATE)})


def test_resting_hr_above_200_rejected(alice_id):
    """INSERT with resting_hr=201 violates CHECK constraint."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_resting_hr|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
                "VALUES (:uid, :d, 201)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=1))})


def test_resting_hr_boundary_20_accepted(alice_id):
    """INSERT with resting_hr=20 (lower boundary) is accepted."""
    test_date = str(BASE_DATE + timedelta(days=2))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
            "VALUES (:uid, :d, 20)"
        ), {"uid": alice_id, "d": test_date})
        conn.execute(text(
            "DELETE FROM daily_metrics WHERE user_id = :uid AND metric_date = :d"
        ), {"uid": alice_id, "d": test_date})


def test_resting_hr_boundary_200_accepted(alice_id):
    """INSERT with resting_hr=200 (upper boundary) is accepted."""
    test_date = str(BASE_DATE + timedelta(days=3))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
            "VALUES (:uid, :d, 200)"
        ), {"uid": alice_id, "d": test_date})
        conn.execute(text(
            "DELETE FROM daily_metrics WHERE user_id = :uid AND metric_date = :d"
        ), {"uid": alice_id, "d": test_date})


def test_resting_hr_null_accepted(alice_id):
    """INSERT with resting_hr=NULL is accepted (nullable column)."""
    test_date = str(BASE_DATE + timedelta(days=4))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
            "VALUES (:uid, :d, NULL)"
        ), {"uid": alice_id, "d": test_date})
        conn.execute(text(
            "DELETE FROM daily_metrics WHERE user_id = :uid AND metric_date = :d"
        ), {"uid": alice_id, "d": test_date})


# ── AC: hrv CHECK constraint ──────────────────────────────────────────────────

def test_hrv_below_0_rejected(alice_id):
    """INSERT with hrv=-1 violates CHECK (must be 0–300)."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_hrv|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, hrv) "
                "VALUES (:uid, :d, -1)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=5))})


def test_hrv_above_300_rejected(alice_id):
    """INSERT with hrv=301 violates CHECK constraint."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_hrv|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, hrv) "
                "VALUES (:uid, :d, 301)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=6))})


# ── AC: sleep_hours CHECK constraint ─────────────────────────────────────────

def test_sleep_hours_above_24_rejected(alice_id):
    """INSERT with sleep_hours=24.5 violates CHECK (must be 0–24)."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_sleep_hours|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, sleep_hours) "
                "VALUES (:uid, :d, 24.5)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=7))})


# ── AC: sleep_quality / energy / mood CHECK constraints (1–5) ────────────────

def test_sleep_quality_zero_rejected(alice_id):
    """INSERT with sleep_quality=0 violates CHECK (must be 1–5)."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_sleep_quality|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, sleep_quality) "
                "VALUES (:uid, :d, 0)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=8))})


def test_sleep_quality_six_rejected(alice_id):
    """INSERT with sleep_quality=6 violates CHECK constraint."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_sleep_quality|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, sleep_quality) "
                "VALUES (:uid, :d, 6)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=9))})


def test_energy_zero_rejected(alice_id):
    """INSERT with energy=0 violates CHECK (must be 1–5)."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_energy|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, energy) "
                "VALUES (:uid, :d, 0)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=10))})


def test_mood_six_rejected(alice_id):
    """INSERT with mood=6 violates CHECK (must be 1–5)."""
    with pytest.raises(IntegrityError, match="ck_daily_metrics_mood|check"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, mood) "
                "VALUES (:uid, :d, 6)"
            ), {"uid": alice_id, "d": str(BASE_DATE + timedelta(days=11))})


# ── AC / Step 4: unique constraint on (user_id, metric_date) ─────────────────

def test_duplicate_user_metric_date_rejected(alice_id):
    """Second INSERT for the same (user_id, metric_date) violates unique constraint."""
    test_date = str(BASE_DATE + timedelta(days=20))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
            "VALUES (:uid, :d, 55)"
        ), {"uid": alice_id, "d": test_date})

    with pytest.raises(IntegrityError, match="uq_daily_metrics_user_date|unique"):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
                "VALUES (:uid, :d, 60)"
            ), {"uid": alice_id, "d": test_date})

    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM daily_metrics WHERE user_id = :uid AND metric_date = :d"
        ), {"uid": alice_id, "d": test_date})


# ── AC / Step 5: updated_at refreshed on UPDATE via trigger ──────────────────

def test_updated_at_trigger_refreshes_on_update(alice_id):
    """UPDATE notes → updated_at reflects the change via the trigger."""
    test_date = str(BASE_DATE + timedelta(days=30))
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO daily_metrics (user_id, metric_date, notes) "
                "VALUES (:uid, :d, 'initial note')"
            ), {"uid": alice_id, "d": test_date})

        with engine.connect() as conn:
            before = conn.execute(text(
                "SELECT updated_at FROM daily_metrics "
                "WHERE user_id = :uid AND metric_date = :d"
            ), {"uid": alice_id, "d": test_date}).fetchone()

        time.sleep(1.1)  # ensure clock advances past 1-second resolution

        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE daily_metrics SET notes = 'updated note' "
                "WHERE user_id = :uid AND metric_date = :d"
            ), {"uid": alice_id, "d": test_date})

        with engine.connect() as conn:
            after = conn.execute(text(
                "SELECT updated_at FROM daily_metrics "
                "WHERE user_id = :uid AND metric_date = :d"
            ), {"uid": alice_id, "d": test_date}).fetchone()

        assert after.updated_at > before.updated_at, (
            f"updated_at was not refreshed after UPDATE: "
            f"before={before.updated_at}, after={after.updated_at}"
        )
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM daily_metrics WHERE user_id = :uid AND metric_date = :d"
            ), {"uid": alice_id, "d": test_date})


# ── AC / Step 6: cascade delete when user is deleted ─────────────────────────

def test_cascade_delete_removes_daily_metrics_on_user_delete():
    """Deleting a user cascades to all their daily_metrics rows."""
    test_user_name = f"test_user_{uuid.uuid4().hex[:8]}"
    test_date = str(BASE_DATE + timedelta(days=40))

    with engine.begin() as conn:
        uid_row = conn.execute(text(
            "INSERT INTO users (name) VALUES (:name) RETURNING id"
        ), {"name": test_user_name}).fetchone()
        uid = str(uid_row.id)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO daily_metrics (user_id, metric_date, resting_hr) "
            "VALUES (:uid, :d, 55)"
        ), {"uid": uid, "d": test_date})

    with engine.connect() as conn:
        count_before = conn.execute(text(
            "SELECT COUNT(*) FROM daily_metrics WHERE user_id = :uid"
        ), {"uid": uid}).scalar()
    assert count_before == 1, "Test row not inserted"

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    with engine.connect() as conn:
        count_after = conn.execute(text(
            "SELECT COUNT(*) FROM daily_metrics WHERE user_id = :uid"
        ), {"uid": uid}).scalar()
    assert count_after == 0, (
        f"Expected cascade delete to remove daily_metrics rows, but {count_after} remain"
    )
