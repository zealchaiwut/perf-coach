"""
Tests for issue #1034: Parse Health Sync sleep CSV into sleep_records.

Acceptance criteria verified:
- AC2: CSV columns mapped to sleep_records schema (Start→start_at, End→end_at, etc.)
- AC3: Timestamps parsed with user timezone; sleep_date = calendar date of start.
- AC4: Upsert on (user_id, external_id) — re-import produces no duplicates.
- AC5: Optional blank stage columns stored as NULL, not 0.
- AC6: Malformed rows skipped; skipped count returned.
- AC7: Unit test loads sample CSV, asserts expected field values, no duplicates on re-run.
- AC8: Parser returns { inserted, updated, skipped, errors[] }.

Runs as pure unit tests (no external DB or Drive required).
DB upsert tests run against UAT Postgres if DATABASE_URL_UAT is set in .env.
"""
import datetime
import hashlib
import pathlib
import uuid

import pytest

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sleep_sample__1034.csv"
_SAMPLE_CSV = _FIXTURE.read_text()

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TZ = "UTC"


# ── helpers ───────────────────────────────────────────────────────────────────

def _import():
    from services.health_sync.sleep_csv_parser import parse_sleep_csv
    return parse_sleep_csv


# ── AC7: sample CSV parses correctly ─────────────────────────────────────────

def test_sample_csv_returns_correct_row_count():
    """7 valid rows + 1 missing-Start (skipped) + 1 blank-stages row = 8 parsed rows (AC7)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    assert len(result["rows"]) == 8


def test_sample_csv_skipped_count():
    """One row with missing Start is skipped; skipped=1 (AC6/AC7)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    assert result["skipped"] == 1


# ── AC8: result shape ─────────────────────────────────────────────────────────

def test_result_has_required_keys():
    """Result has inserted, updated, skipped, errors, rows keys (AC8)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    assert "inserted" in result
    assert "updated" in result
    assert "skipped" in result
    assert "errors" in result
    assert "rows" in result


# ── AC2: column mapping ────────────────────────────────────────────────────────

def test_start_at_mapped_correctly():
    """'Start' column → start_at DateTime (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert "start_at" in first
    assert isinstance(first["start_at"], datetime.datetime)
    assert first["start_at"].year == 2024
    assert first["start_at"].month == 3
    assert first["start_at"].day == 1
    assert first["start_at"].hour == 22
    assert first["start_at"].minute == 15


def test_end_at_mapped_correctly():
    """'End' column → end_at DateTime (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert "end_at" in first
    assert isinstance(first["end_at"], datetime.datetime)
    assert first["end_at"].day == 2
    assert first["end_at"].hour == 6
    assert first["end_at"].minute == 30


def test_total_sleep_minutes_mapped():
    """'Sleep Duration' HH:MM:SS → total_sleep_minutes int (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert first["total_sleep_minutes"] == 7 * 60 + 45  # 07:45:00


def test_deep_minutes_mapped():
    """'Deep Sleep' → deep_minutes int (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert first["deep_minutes"] == 90  # 01:30:00


def test_rem_minutes_mapped():
    """'REM Sleep' → rem_minutes int (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert first["rem_minutes"] == 105  # 01:45:00


def test_light_minutes_mapped():
    """'Light Sleep' → light_minutes int (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert first["light_minutes"] == 255  # 04:15:00


def test_awake_minutes_mapped():
    """'Awake Time' → awake_minutes int (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert first["awake_minutes"] == 30  # 00:30:00


def test_time_in_bed_minutes_computed():
    """time_in_bed_minutes derived from end_at - start_at (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    # 22:15 to 06:30 next day = 8h15m = 495 minutes
    assert first["time_in_bed_minutes"] == 495


def test_source_is_health_sync_csv():
    """source = 'health_sync_csv' for all parsed rows (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    for row in result["rows"]:
        assert row["source"] == "health_sync_csv"


def test_heart_rate_and_spo2_not_in_rows():
    """Heart Rate and SpO2 columns are not persisted (no schema column) (AC2)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    for row in result["rows"]:
        assert "heart_rate" not in row
        assert "spo2" not in row


# ── AC3: timezone and sleep_date ──────────────────────────────────────────────

def test_sleep_date_is_local_date_of_start():
    """sleep_date = calendar date of start_at in user timezone (AC3)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    assert first["sleep_date"] == datetime.date(2024, 3, 1)


def test_timezone_applied_to_timestamps():
    """Timestamps have tzinfo set (AC3)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    for row in result["rows"]:
        assert row["start_at"].tzinfo is not None
        assert row["end_at"].tzinfo is not None


def test_timezone_bangkok():
    """UTC+7 timezone shifts times correctly (AC3)."""
    parse = _import()
    # Row 1: Start = "2024-03-01 22:15:00" in Asia/Bangkok (UTC+7)
    result = parse(_SAMPLE_CSV, _USER_ID, "Asia/Bangkok")
    first = result["rows"][0]
    # sleep_date should still be 2024-03-01 (local date of start)
    assert first["sleep_date"] == datetime.date(2024, 3, 1)
    # start_at should carry +07:00 offset
    assert first["start_at"].utcoffset().total_seconds() == 7 * 3600


# ── AC4: external_id and idempotency ─────────────────────────────────────────

def test_external_id_is_sha256_hash():
    """external_id = SHA-256('{user_id}:{sleep_date}:{start_at_iso}') (AC4)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    first = result["rows"][0]
    sleep_date = first["sleep_date"].isoformat()
    start_at = first["start_at"].isoformat()
    expected = hashlib.sha256(
        f"{_USER_ID}:{sleep_date}:{start_at}".encode()
    ).hexdigest()
    assert first["external_id"] == expected


def test_parse_twice_same_external_ids():
    """Parsing same CSV twice produces identical external_ids (idempotent keys) (AC4)."""
    parse = _import()
    r1 = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    r2 = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    ids1 = [row["external_id"] for row in r1["rows"]]
    ids2 = [row["external_id"] for row in r2["rows"]]
    assert ids1 == ids2


def test_no_duplicate_external_ids_in_one_parse():
    """All external_ids are unique within one parse result (AC4)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    ids = [row["external_id"] for row in result["rows"]]
    assert len(ids) == len(set(ids))


# ── AC5: optional blank columns → NULL ────────────────────────────────────────

def test_blank_stage_columns_are_none():
    """Row with blank Deep/REM/Light/Awake columns → None (not 0) (AC5)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    # Last row in sample CSV has blank stage columns (row index 7, 0-based)
    blank_row = result["rows"][-1]
    assert blank_row["deep_minutes"] is None, "deep_minutes should be None when blank"
    assert blank_row["rem_minutes"] is None, "rem_minutes should be None when blank"
    assert blank_row["light_minutes"] is None, "light_minutes should be None when blank"
    assert blank_row["awake_minutes"] is None, "awake_minutes should be None when blank"


def test_blank_stage_row_still_has_required_fields():
    """Row with blank stages still has valid start_at, end_at, total_sleep_minutes (AC5)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    blank_row = result["rows"][-1]
    assert blank_row["start_at"] is not None
    assert blank_row["end_at"] is not None
    assert blank_row["total_sleep_minutes"] == 7 * 60 + 30  # 07:30:00


# ── AC6: malformed row skipping ────────────────────────────────────────────────

def test_missing_start_row_is_skipped():
    """Row with empty Start field is skipped (not in rows) (AC6)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    # All rows should have a valid start_at
    for row in result["rows"]:
        assert row["start_at"] is not None


def test_malformed_row_error_is_recorded():
    """Skipped malformed row is recorded in errors list (AC6)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    assert len(result["errors"]) >= 1


def test_malformed_row_does_not_abort_remaining():
    """Processing continues after skipping a malformed row (AC6)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    # Should parse 8 valid rows (7 full + 1 with blank stages)
    # even though 1 malformed row (missing Start) exists
    assert len(result["rows"]) == 8


def test_custom_malformed_csv_skipped_and_rest_parsed():
    """A single-bad-row CSV skips the bad row and returns the good one (AC6)."""
    parse = _import()
    csv = (
        "Start,End,Sleep Duration,Deep Sleep,REM Sleep,Light Sleep,Awake Time,Heart Rate,SpO2\n"
        "NOT_A_DATE,2024-04-02 07:00:00,07:00:00,01:00:00,01:30:00,04:00:00,00:30:00,58,97\n"
        "2024-04-02 22:00:00,2024-04-03 06:00:00,07:30:00,01:30:00,01:30:00,04:00:00,00:30:00,59,98\n"
    )
    result = parse(csv, _USER_ID, _TZ)
    assert result["skipped"] == 1
    assert len(result["rows"]) == 1
    assert len(result["errors"]) == 1


# ── AC8: inserted/updated/skipped initialised ─────────────────────────────────

def test_parse_only_does_not_count_db_ops():
    """parse_sleep_csv (no DB) returns inserted=0, updated=0 (AC8)."""
    parse = _import()
    result = parse(_SAMPLE_CSV, _USER_ID, _TZ)
    assert result["inserted"] == 0
    assert result["updated"] == 0


# ── DB upsert tests (requires UAT Postgres) ───────────────────────────────────

def _get_uat_engine():
    import pathlib
    from dotenv import dotenv_values
    root = pathlib.Path(__file__).resolve().parents[1]
    vals = dotenv_values(root / ".env")
    url = vals.get("DATABASE_URL_UAT")
    if not url:
        return None
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True)


def _alice_id(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM users WHERE name = 'Alice'")).fetchone()
    assert row is not None, "Alice not found"
    return row.id


def test_upsert_inserts_rows():
    """upsert_sleep_records inserts new rows and returns correct inserted count (AC4/AC8)."""
    engine = _get_uat_engine()
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from services.health_sync.sleep_csv_parser import parse_sleep_csv, upsert_sleep_records

    user_id = _alice_id(engine)
    result = parse_sleep_csv(_SAMPLE_CSV, user_id, "UTC")
    rows = result["rows"]

    ext_ids = [r["external_id"] for r in rows]
    with Session(engine) as session:
        try:
            summary = upsert_sleep_records(rows, session)
            session.commit()
            assert summary["inserted"] + summary["updated"] == len(rows)
        except Exception:
            session.rollback()
            raise
        finally:
            # cleanup: remove test rows
            session.rollback()
            session.execute(
                text("DELETE FROM sleep_records WHERE user_id = :uid AND external_id = ANY(:ids)"),
                {"uid": str(user_id), "ids": ext_ids},
            )
            session.commit()


def test_upsert_idempotent_no_duplicates():
    """Re-importing same CSV produces no duplicate rows in sleep_records (AC4/UAT4)."""
    engine = _get_uat_engine()
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from services.health_sync.sleep_csv_parser import parse_sleep_csv, upsert_sleep_records

    user_id = _alice_id(engine)
    result = parse_sleep_csv(_SAMPLE_CSV, user_id, "UTC")
    rows = result["rows"]
    ext_ids = [r["external_id"] for r in rows]

    with Session(engine) as session:
        try:
            upsert_sleep_records(rows, session)
            session.commit()

            # Second import
            upsert_sleep_records(rows, session)
            session.commit()

            count = session.execute(
                text(
                    "SELECT COUNT(*) FROM sleep_records "
                    "WHERE user_id = :uid AND external_id = ANY(:ids)"
                ),
                {"uid": str(user_id), "ids": ext_ids},
            ).scalar()
            assert count == len(rows), f"Expected {len(rows)} rows, got {count}"
        except Exception:
            session.rollback()
            raise
        finally:
            session.rollback()
            session.execute(
                text("DELETE FROM sleep_records WHERE user_id = :uid AND external_id = ANY(:ids)"),
                {"uid": str(user_id), "ids": ext_ids},
            )
            session.commit()


def test_upsert_stage_null_stored_as_null():
    """Blank-stage row persisted with NULL stage columns, not 0 (AC5/UAT6)."""
    engine = _get_uat_engine()
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from services.health_sync.sleep_csv_parser import parse_sleep_csv, upsert_sleep_records

    user_id = _alice_id(engine)
    result = parse_sleep_csv(_SAMPLE_CSV, user_id, "UTC")
    rows = result["rows"]
    blank_row = rows[-1]
    ext_ids = [r["external_id"] for r in rows]

    with Session(engine) as session:
        try:
            upsert_sleep_records(rows, session)
            session.commit()

            db_row = session.execute(
                text(
                    "SELECT deep_minutes, rem_minutes, light_minutes, awake_minutes "
                    "FROM sleep_records WHERE user_id = :uid AND external_id = :eid"
                ),
                {"uid": str(user_id), "eid": blank_row["external_id"]},
            ).fetchone()
            assert db_row is not None
            assert db_row.deep_minutes is None
            assert db_row.rem_minutes is None
            assert db_row.light_minutes is None
            assert db_row.awake_minutes is None
        except Exception:
            session.rollback()
            raise
        finally:
            session.rollback()
            session.execute(
                text("DELETE FROM sleep_records WHERE user_id = :uid AND external_id = ANY(:ids)"),
                {"uid": str(user_id), "ids": ext_ids},
            )
            session.commit()
