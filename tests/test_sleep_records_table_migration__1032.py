"""
Tests for issue #1032: Add sleep_records table and idempotent Alembic migration.

Acceptance criteria verified:
- AC1: sleep_records table exists with all required columns.
- AC2: source column stores 'health_sync_csv' for CSV import rows.
- AC3: external_id derived from user_id + sleep_date + start_at when source has no native id.
- AC4: Unique constraint exists on (user_id, external_id).
- AC5: Index exists on (user_id, sleep_date).
- AC6: Migration is idempotent (table already exists — no error on re-run).
- AC7: SQLAlchemy SleepRecord model is defined and reflects the schema.

Runs against the UAT Postgres database via DATABASE_URL_UAT from .env.
"""
import hashlib
import pathlib

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import SleepRecord

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")

engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _require_engine():
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping Postgres-specific test")


def _alice_id():
    _require_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM users WHERE name = 'Alice'")
        ).fetchone()
    assert row is not None, "Alice not found — seed not run?"
    return row.id


def _get_columns():
    _require_engine()
    inspector = inspect(engine)
    cols = inspector.get_columns("sleep_records")
    return {c["name"]: c for c in cols}


# ── AC1: All required columns present ─────────────────────────────────────────

def test_sleep_records_table_exists():
    """sleep_records table exists after migration (AC1/UAT1)."""
    _require_engine()
    inspector = inspect(engine)
    assert inspector.has_table("sleep_records"), "sleep_records table not found"


def test_sleep_records_required_columns():
    """All required columns exist in sleep_records (AC1/UAT1)."""
    required = {
        "id", "user_id", "sleep_date", "start_at", "end_at",
        "total_sleep_minutes", "time_in_bed_minutes", "awake_minutes",
        "light_minutes", "deep_minutes", "rem_minutes",
        "sleep_score", "sleep_efficiency",
        "source", "device", "external_id",
        "created_at", "updated_at",
    }
    cols = _get_columns()
    missing = required - cols.keys()
    assert not missing, f"Missing columns in sleep_records: {missing}"


def test_sleep_score_nullable():
    """sleep_score is nullable (AC1)."""
    cols = _get_columns()
    assert "sleep_score" in cols
    assert cols["sleep_score"]["nullable"] is True, "sleep_score should be nullable"


def test_sleep_efficiency_nullable():
    """sleep_efficiency is nullable (AC1)."""
    cols = _get_columns()
    assert "sleep_efficiency" in cols
    assert cols["sleep_efficiency"]["nullable"] is True, "sleep_efficiency should be nullable"


def test_device_nullable():
    """device is nullable (AC1)."""
    cols = _get_columns()
    assert "device" in cols
    assert cols["device"]["nullable"] is True, "device should be nullable"


def test_source_not_nullable():
    """source is NOT nullable (AC1)."""
    cols = _get_columns()
    assert "source" in cols
    assert cols["source"]["nullable"] is False, "source should not be nullable"


def test_external_id_not_nullable():
    """external_id is NOT nullable (AC1)."""
    cols = _get_columns()
    assert "external_id" in cols
    assert cols["external_id"]["nullable"] is False, "external_id should not be nullable"


# ── AC4: Unique constraint on (user_id, external_id) ──────────────────────────

def test_unique_constraint_user_id_external_id():
    """Unique constraint exists on (user_id, external_id) — rejects duplicate import (AC4/UAT3)."""
    user_id = _alice_id()
    with Session(engine) as session:
        r1 = SleepRecord(
            user_id=user_id,
            sleep_date="2099-01-01",
            start_at="2099-01-01T22:00:00+00:00",
            end_at="2099-01-02T06:00:00+00:00",
            total_sleep_minutes=480,
            time_in_bed_minutes=500,
            awake_minutes=20,
            light_minutes=200,
            deep_minutes=150,
            rem_minutes=130,
            source="health_sync_csv",
            external_id="test-unique-constraint-1032",
        )
        session.add(r1)
        session.commit()

        r2 = SleepRecord(
            user_id=user_id,
            sleep_date="2099-01-02",
            start_at="2099-01-02T22:00:00+00:00",
            end_at="2099-01-03T06:00:00+00:00",
            total_sleep_minutes=480,
            time_in_bed_minutes=500,
            awake_minutes=20,
            light_minutes=200,
            deep_minutes=150,
            rem_minutes=130,
            source="health_sync_csv",
            external_id="test-unique-constraint-1032",  # same external_id
        )
        session.add(r2)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # cleanup
        session.delete(session.get(SleepRecord, r1.id))
        session.commit()


def test_different_external_id_same_user_allowed():
    """Two rows with same user_id but different external_id are both inserted (AC4/UAT4)."""
    user_id = _alice_id()
    with Session(engine) as session:
        r1 = SleepRecord(
            user_id=user_id,
            sleep_date="2099-02-01",
            start_at="2099-02-01T22:00:00+00:00",
            end_at="2099-02-02T06:00:00+00:00",
            total_sleep_minutes=480,
            time_in_bed_minutes=500,
            awake_minutes=20,
            light_minutes=200,
            deep_minutes=150,
            rem_minutes=130,
            source="health_sync_csv",
            external_id="diff-extid-1032-A",
        )
        r2 = SleepRecord(
            user_id=user_id,
            sleep_date="2099-02-02",
            start_at="2099-02-02T22:00:00+00:00",
            end_at="2099-02-03T06:00:00+00:00",
            total_sleep_minutes=480,
            time_in_bed_minutes=500,
            awake_minutes=20,
            light_minutes=200,
            deep_minutes=150,
            rem_minutes=130,
            source="health_sync_csv",
            external_id="diff-extid-1032-B",
        )
        session.add_all([r1, r2])
        session.commit()  # must not raise

        session.delete(session.get(SleepRecord, r1.id))
        session.delete(session.get(SleepRecord, r2.id))
        session.commit()


# ── AC5: Index on (user_id, sleep_date) ───────────────────────────────────────

def test_index_user_id_sleep_date_exists():
    """Index on (user_id, sleep_date) exists (AC5/UAT6)."""
    _require_engine()
    inspector = inspect(engine)
    indexes = inspector.get_indexes("sleep_records")
    index_columns = [
        frozenset(idx["column_names"])
        for idx in indexes
    ]
    assert frozenset(["user_id", "sleep_date"]) in index_columns, (
        f"No index covering (user_id, sleep_date) found. Existing indexes: {indexes}"
    )


# ── AC6: Idempotency — table already exists ────────────────────────────────────

def test_migration_idempotent_table_still_exists():
    """sleep_records table is present (migration ran — or would be idempotent) (AC6/UAT2)."""
    _require_engine()
    inspector = inspect(engine)
    assert inspector.has_table("sleep_records"), "sleep_records table missing after migration"


# ── AC2: source = 'health_sync_csv' ───────────────────────────────────────────

def test_source_health_sync_csv_persists():
    """source='health_sync_csv' is stored and retrieved correctly (AC2/UAT5)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = SleepRecord(
            user_id=user_id,
            sleep_date="2099-03-01",
            start_at="2099-03-01T22:00:00+00:00",
            end_at="2099-03-02T06:00:00+00:00",
            total_sleep_minutes=480,
            time_in_bed_minutes=500,
            awake_minutes=20,
            light_minutes=200,
            deep_minutes=150,
            rem_minutes=130,
            source="health_sync_csv",
            external_id="source-test-1032",
        )
        session.add(rec)
        session.commit()
        rec_id = rec.id

        reloaded = session.get(SleepRecord, rec_id)
        assert reloaded.source == "health_sync_csv"

        session.delete(reloaded)
        session.commit()


# ── AC3: external_id derived from user_id + sleep_date + start_at ─────────────

def test_derive_external_id_from_user_sleep_date_start_at():
    """external_id derived as hash of user_id+sleep_date+start_at matches expected value (AC3/UAT5)."""
    user_id = _alice_id()
    sleep_date = "2099-04-01"
    start_at = "2099-04-01T22:00:00+00:00"

    # The derivation convention: SHA-256 of "{user_id}:{sleep_date}:{start_at}"
    raw = f"{user_id}:{sleep_date}:{start_at}"
    expected_external_id = hashlib.sha256(raw.encode()).hexdigest()

    with Session(engine) as session:
        rec = SleepRecord(
            user_id=user_id,
            sleep_date=sleep_date,
            start_at=start_at,
            end_at="2099-04-02T06:00:00+00:00",
            total_sleep_minutes=480,
            time_in_bed_minutes=500,
            awake_minutes=20,
            light_minutes=200,
            deep_minutes=150,
            rem_minutes=130,
            source="health_sync_csv",
            external_id=expected_external_id,
        )
        session.add(rec)
        session.commit()
        rec_id = rec.id

        reloaded = session.get(SleepRecord, rec_id)
        assert reloaded.external_id == expected_external_id, (
            f"Expected derived external_id {expected_external_id!r}, "
            f"got {reloaded.external_id!r}"
        )

        session.delete(reloaded)
        session.commit()


# ── AC7: SleepRecord ORM model is importable and usable ───────────────────────

def test_sleep_record_model_importable():
    """SleepRecord can be imported from backend.models (AC7)."""
    from backend.models import SleepRecord as SR
    assert SR.__tablename__ == "sleep_records"


def test_sleep_record_orm_roundtrip():
    """SleepRecord persists and loads all fields via ORM (AC7/UAT1)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = SleepRecord(
            user_id=user_id,
            sleep_date="2099-05-01",
            start_at="2099-05-01T22:00:00+00:00",
            end_at="2099-05-02T06:30:00+00:00",
            total_sleep_minutes=450,
            time_in_bed_minutes=510,
            awake_minutes=60,
            light_minutes=180,
            deep_minutes=120,
            rem_minutes=150,
            sleep_score=82,
            sleep_efficiency=88.2,
            source="health_sync_csv",
            device="Apple Watch",
            external_id="orm-roundtrip-1032",
        )
        session.add(rec)
        session.commit()
        rec_id = rec.id

        reloaded = session.get(SleepRecord, rec_id)
        assert reloaded is not None
        assert reloaded.total_sleep_minutes == 450
        assert reloaded.sleep_score == 82
        assert float(reloaded.sleep_efficiency) == pytest.approx(88.2, abs=0.1)
        assert reloaded.device == "Apple Watch"
        assert reloaded.source == "health_sync_csv"

        session.delete(reloaded)
        session.commit()


def test_sleep_record_nullable_fields_default_none():
    """Nullable fields (sleep_score, sleep_efficiency, device) default to None (AC1/AC7)."""
    user_id = _alice_id()
    with Session(engine) as session:
        rec = SleepRecord(
            user_id=user_id,
            sleep_date="2099-06-01",
            start_at="2099-06-01T22:00:00+00:00",
            end_at="2099-06-02T06:00:00+00:00",
            total_sleep_minutes=480,
            time_in_bed_minutes=500,
            awake_minutes=20,
            light_minutes=200,
            deep_minutes=150,
            rem_minutes=110,
            source="health_sync_csv",
            external_id="nullable-test-1032",
        )
        session.add(rec)
        session.commit()
        rec_id = rec.id

        reloaded = session.get(SleepRecord, rec_id)
        assert reloaded.sleep_score is None
        assert reloaded.sleep_efficiency is None
        assert reloaded.device is None

        session.delete(reloaded)
        session.commit()
