"""Tests for issue #573: Ingest activity streams on Strava and Stryd sync.

Each test is anchored to a specific acceptance criterion (AC) from the issue.

Schema context: activity_streams has workout_id as PK (FK → workouts.id).
Streams are stored as JSONB arrays (one element per second after downsampling).
Stryd streams are cached in stryd_activities.streams_payload during sync;
Strava streams come from strava_activities.streams_payload.
Reconcile reads both and writes to activity_streams after workout_id is known.
"""
import uuid
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.services.activity_streams import (
    downsample_to_1hz,
    extract_strava_streams,
    extract_stryd_streams,
    write_activity_stream,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user() -> str:
    name = f"as573_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
            {"n": name},
        ).fetchone()
    return str(row.id)


def _drop_user(uid: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _make_workout(uid: str) -> str:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO workouts (user_id, workout_date, name, workout_type) "
                "VALUES (:uid, current_date, 'Test run', 'Run') RETURNING id"
            ),
            {"uid": uid},
        ).fetchone()
    return str(row.id)


def _get_stream_row(workout_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM activity_streams WHERE workout_id = :wid"),
            {"wid": workout_id},
        ).fetchone()
    if row is None:
        return None
    return dict(row._mapping)


# ── Fake payloads ─────────────────────────────────────────────────────────────

def _strava_streams_payload(duration_s: int = 5, hz: int = 1) -> dict:
    """Build a synthetic Strava streams dict (key_by_type=true format)."""
    n = duration_s * hz
    step = 1.0 / hz
    time_offsets = [round(i * step, 3) for i in range(n)]
    return {
        "time": {"data": time_offsets, "series_type": "time", "original_size": n},
        "heartrate": {"data": [140 + (i % 20) for i in range(n)], "series_type": "time", "original_size": n},
        "altitude": {"data": [100.0 + i * 0.1 for i in range(n)], "series_type": "time", "original_size": n},
        "cadence": {"data": [80 + (i % 5) for i in range(n)], "series_type": "time", "original_size": n},
        "velocity_smooth": {"data": [3.5 + (i % 5) * 0.1 for i in range(n)], "series_type": "time", "original_size": n},
    }


def _stryd_streams_payload(duration_s: int = 5, hz: int = 1) -> dict:
    """Build a synthetic Stryd per-activity streams dict."""
    n = duration_s * hz
    step = 1.0 / hz
    base_ts = 1_700_000_000
    timestamps = [base_ts + i * step for i in range(n)]
    return {
        "timestamp_list": timestamps,
        "heart_rate_list": [150 + (i % 10) for i in range(n)],
        "total_power_list": [200 + (i % 30) for i in range(n)],
        "cadence_list": [170 + (i % 5) for i in range(n)],
        "speed_list": [3.0 + (i % 5) * 0.1 for i in range(n)],
    }


# ── AC3: Downsampling ─────────────────────────────────────────────────────────

def test_downsample_identity_1hz():
    """AC3: 1 Hz input passes through unchanged (already ≤1 sample/s)."""
    ts = [0, 1, 2, 3, 4]
    vals = [10, 20, 30, 40, 50]
    result = downsample_to_1hz(ts, vals)
    assert result == [(0, 10.0), (1, 20.0), (2, 30.0), (3, 40.0), (4, 50.0)]


def test_downsample_reduces_5hz_to_1hz():
    """AC3: 5 Hz input (0.2 s spacing) is reduced to ≤1 sample/s."""
    ts = [i * 0.2 for i in range(10)]  # 0..1.8 in 0.2 steps → 2 s of data
    vals = list(range(10))
    result = downsample_to_1hz(ts, vals)
    assert len(result) == 2
    buckets = [r[0] for r in result]
    assert buckets == [0, 1]
    # First-sample-in-window: bucket 0 → val=0, bucket 1 → val=5
    assert result[0][1] == 0.0
    assert result[1][1] == 5.0


def test_downsample_empty_input():
    """AC3: Empty input returns empty list without raising."""
    assert downsample_to_1hz([], []) == []


def test_downsample_docstring_example():
    """AC3: Verify the worked example from the function docstring."""
    ts = [0, 0.2, 0.4, 1.0, 1.2, 1.8]
    vals = [10, 11, 12, 20, 21, 22]
    result = downsample_to_1hz(ts, vals)
    assert result == [(0, 10.0), (1, 20.0)]


def test_downsample_skips_non_numeric():
    """AC4: Non-numeric values are silently dropped."""
    ts = [0, 1, 2]
    vals = [10, None, 30]
    result = downsample_to_1hz(ts, vals)
    assert len(result) == 2
    assert result[0] == (0, 10.0)
    assert result[1] == (2, 30.0)


# ── AC1/AC4/AC5: extract_strava_streams ──────────────────────────────────────

def test_extract_strava_produces_row_with_source_strava():
    """AC1, AC5: Row has source='strava' and contains channel arrays."""
    payload = _strava_streams_payload(duration_s=3, hz=1)
    row, err = extract_strava_streams(payload)
    assert err is None
    assert row
    assert row["source"] == "strava"


def test_extract_strava_channels_present():
    """AC1: Channels present in payload produce arrays."""
    payload = _strava_streams_payload(duration_s=3, hz=1)
    row, err = extract_strava_streams(payload)
    assert err is None
    assert "heart_rate_bpm" in row
    assert "altitude_m" in row
    assert "cadence_spm" in row
    assert "pace_seconds_per_km" in row
    assert "time_offset_seconds" in row


def test_extract_strava_missing_channel_silently_skipped():
    """AC4: Absent channel (watts/power) is silently skipped; others continue."""
    payload = _strava_streams_payload(duration_s=3, hz=1)
    # watts not in payload
    row, err = extract_strava_streams(payload)
    assert err is None
    assert "power_w" not in row
    assert "heart_rate_bpm" in row


def test_extract_strava_missing_payload_returns_null():
    """AC6: None payload → null + human-readable reason."""
    row, err = extract_strava_streams(None)
    assert row is None
    assert err and "payload" in err.lower()


def test_extract_strava_missing_time_stream_returns_null():
    """AC6: Payload without time stream → null + reason."""
    payload = {"heartrate": {"data": [140, 145], "series_type": "time", "original_size": 2}}
    row, err = extract_strava_streams(payload)
    assert row is None
    assert err and "time" in err.lower()


def test_extract_strava_5hz_downsampled():
    """AC3/UAT step 5: 5 Hz input → at most 1 sample/s in the stored arrays."""
    duration_s = 10
    payload = _strava_streams_payload(duration_s=duration_s, hz=5)
    row, err = extract_strava_streams(payload)
    assert err is None
    hr_arr = row.get("heart_rate_bpm") or []
    # Stored array length should equal duration_s (1 sample/s after downsampling)
    assert len(hr_arr) == duration_s


def test_extract_strava_pace_computed_from_velocity():
    """AC1: velocity_smooth (m/s) → pace_seconds_per_km stored correctly."""
    # 4.0 m/s = 250 s/km
    payload = {
        "time": {"data": [0, 1, 2], "series_type": "time", "original_size": 3},
        "velocity_smooth": {"data": [4.0, 4.0, 4.0], "series_type": "time", "original_size": 3},
    }
    row, err = extract_strava_streams(payload)
    assert err is None
    pace = row.get("pace_seconds_per_km") or []
    assert len(pace) == 3
    assert abs(pace[0] - 250.0) < 0.1


def test_extract_strava_no_hardcoded_thresholds():
    """AC7: No hardcoded threshold values in the service module."""
    import inspect
    import backend.services.activity_streams as mod
    src = inspect.getsource(mod)
    for forbidden in ("220 -", "max_hr =", "min_pace =", "max_pace ="):
        assert forbidden not in src, f"Hardcoded threshold found: {forbidden!r}"


# ── AC2/AC4/AC5: extract_stryd_streams ───────────────────────────────────────

def test_extract_stryd_produces_row_with_source_stryd():
    """AC2, AC5: Row has source='stryd'."""
    payload = _stryd_streams_payload(duration_s=3, hz=1)
    row, err = extract_stryd_streams(payload)
    assert err is None
    assert row
    assert row["source"] == "stryd"


def test_extract_stryd_channels_present():
    """AC2: Channels present in payload produce arrays."""
    payload = _stryd_streams_payload(duration_s=3, hz=1)
    row, err = extract_stryd_streams(payload)
    assert err is None
    assert "heart_rate_bpm" in row
    assert "power_w" in row
    assert "cadence_spm" in row
    assert "pace_seconds_per_km" in row
    assert "time_offset_seconds" in row


def test_extract_stryd_missing_channel_skipped():
    """AC4: Absent channel (stride_length, not in schema anyway) silently skipped."""
    payload = _stryd_streams_payload(duration_s=3, hz=1)
    # speed_list removed
    del payload["speed_list"]
    row, err = extract_stryd_streams(payload)
    assert err is None
    assert "pace_seconds_per_km" not in row
    assert "heart_rate_bpm" in row


def test_extract_stryd_missing_payload_returns_null():
    """AC6: None payload → null + reason."""
    row, err = extract_stryd_streams(None)
    assert row is None
    assert err


def test_extract_stryd_missing_timestamp_list_returns_null():
    """AC6: Missing timestamp_list → null + reason."""
    payload = {"heart_rate_list": [150, 152]}
    row, err = extract_stryd_streams(payload)
    assert row is None
    assert err and "timestamp" in err.lower()


def test_extract_stryd_normalises_ms_timestamps():
    """AC2: Stryd ms-epoch timestamps are normalised to seconds."""
    base_ms = 1_700_000_000_000  # milliseconds
    payload = {
        "timestamp_list": [base_ms, base_ms + 1000, base_ms + 2000],
        "heart_rate_list": [150, 151, 152],
    }
    row, err = extract_stryd_streams(payload)
    assert err is None
    assert row
    offsets = row.get("time_offset_seconds") or []
    # Offsets should be [0, 1, 2]
    assert offsets == [0, 1, 2]


def test_extract_stryd_second_aligned_no_sub_second_gaps():
    """AC2/AC3: After downsampling 5 Hz → unique second-aligned offsets."""
    payload = _stryd_streams_payload(duration_s=5, hz=5)
    row, err = extract_stryd_streams(payload)
    assert err is None
    offsets = row.get("time_offset_seconds") or []
    assert len(offsets) == len(set(offsets)), "Duplicate time offsets found after downsampling"


def test_extract_stryd_5hz_downsampled_to_1hz():
    """AC3/UAT step 3: 5 Hz input stored at ≤1 sample/s."""
    duration_s = 5
    payload = _stryd_streams_payload(duration_s=duration_s, hz=5)
    row, err = extract_stryd_streams(payload)
    assert err is None
    hr_arr = row.get("heart_rate_bpm") or []
    assert len(hr_arr) <= duration_s


# ── AC8: pure-function separation ─────────────────────────────────────────────

def test_stream_logic_has_no_top_level_db_imports():
    """AC8: activity_streams module does not import db/engine at the top level."""
    import ast
    import pathlib
    src = pathlib.Path("backend/services/activity_streams.py").read_text()
    tree = ast.parse(src)
    top_imports = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom)) and n.col_offset == 0
    ]
    bad = [
        n for n in top_imports
        if (
            "db" in (getattr(n, "module", "") or "")
            or any("db" in alias.name for alias in getattr(n, "names", []))
        )
    ]
    assert not bad, f"Top-level DB imports found: {bad}"


# ── DB write (write_activity_stream) ─────────────────────────────────────────

def test_write_activity_stream_inserts_row():
    """AC1/AC2: write_activity_stream persists a row to activity_streams."""
    uid = _make_user()
    try:
        wid = _make_workout(uid)
        row_data = {
            "source": "strava",
            "sample_interval_seconds": 1,
            "time_offset_seconds": [0, 1, 2],
            "heart_rate_bpm": [140, 141, 142],
        }
        with Session(engine) as session:
            write_activity_stream(wid, row_data, session)
            session.commit()
        stored = _get_stream_row(wid)
        assert stored is not None
        assert stored["source"] == "strava"
        assert stored["heart_rate_bpm"] == [140, 141, 142]
    finally:
        _drop_user(uid)


def test_write_activity_stream_idempotent():
    """AC10/UAT step 6: Re-writing the same workout_id updates, not duplicates."""
    uid = _make_user()
    try:
        wid = _make_workout(uid)
        first = {
            "source": "strava",
            "sample_interval_seconds": 1,
            "heart_rate_bpm": [140, 141],
        }
        second = {
            "source": "strava",
            "sample_interval_seconds": 1,
            "heart_rate_bpm": [150, 151],
        }
        with Session(engine) as session:
            write_activity_stream(wid, first, session)
            session.commit()
        with Session(engine) as session:
            write_activity_stream(wid, second, session)
            session.commit()
        # Only one row; HR updated to second write
        stored = _get_stream_row(wid)
        assert stored is not None
        assert stored["heart_rate_bpm"] == [150, 151]
        # Confirm only one row exists
        with engine.connect() as conn:
            cnt = conn.execute(
                text("SELECT COUNT(*) FROM activity_streams WHERE workout_id = :wid"),
                {"wid": wid},
            ).scalar()
        assert cnt == 1
    finally:
        _drop_user(uid)


def test_write_activity_stream_empty_noop():
    """write_activity_stream with empty dict is a no-op."""
    with Session(engine) as session:
        result = write_activity_stream("00000000-0000-0000-0000-000000000001", {}, session)
    assert result is False


def test_write_activity_stream_source_stored():
    """AC5: source field is persisted correctly."""
    uid = _make_user()
    try:
        wid = _make_workout(uid)
        with Session(engine) as session:
            write_activity_stream(wid, {"source": "stryd", "sample_interval_seconds": 1}, session)
            session.commit()
        stored = _get_stream_row(wid)
        assert stored["source"] == "stryd"
    finally:
        _drop_user(uid)


# ── AC1: Strava sync integration ──────────────────────────────────────────────

def test_strava_sync_and_reconcile_writes_activity_streams():
    """AC1/AC9: Strava sync + reconcile writes activity_streams; existing flows unaffected."""
    from backend.services.strava_sync import sync_strava_activities
    from backend.services.reconcile import reconcile_workouts

    uid = _make_user()
    activity_id = 9_991_001
    streams = _strava_streams_payload(duration_s=5, hz=1)

    fake_activity = {
        "id": activity_id,
        "name": "Test run",
        "type": "Run",
        "sport_type": "Run",
        "start_date": "2023-11-14T22:13:20Z",
        "distance": 10000.0,
        "moving_time": 300,
        "average_heartrate": 145,
        "max_heartrate": 175,
        "total_elevation_gain": 100,
        "average_watts": None,
        "max_watts": None,
        "device_name": "Garmin",
        "external_id": f"ext-{activity_id}",
    }

    try:
        # Step 1: Sync (stores streams in strava_activities.streams_payload)
        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter([fake_activity])), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False), \
             patch("backend.services.strava_sync.get_activity_detail", return_value=fake_activity), \
             patch("backend.services.strava_sync.get_activity_streams", return_value=streams):
            result = sync_strava_activities(user_id=uid)
        assert result["status"] == "completed"
        assert result["activities_created"] == 1

        # Step 2: Reconcile (creates workout, writes activity_streams)
        reconcile_workouts(job_id=None, user_id=uid)

        # Verify: workout exists and has a stream row
        with engine.connect() as conn:
            wid = conn.execute(
                text("SELECT id FROM workouts WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"),
                {"uid": uid},
            ).scalar()
        assert wid is not None

        stream_row = _get_stream_row(str(wid))
        assert stream_row is not None, "activity_streams row should exist after reconcile"
        assert stream_row["source"] == "strava"
        assert stream_row.get("heart_rate_bpm") is not None
    finally:
        _drop_user(uid)


def test_strava_sync_activity_without_streams_still_succeeds():
    """AC9: Activity with empty streams does not error; workflow continues."""
    from backend.services.strava_sync import sync_strava_activities
    from backend.services.reconcile import reconcile_workouts

    uid = _make_user()
    activity_id = 9_991_002

    fake_activity = {
        "id": activity_id,
        "name": "Manual entry",
        "type": "Run",
        "sport_type": "Run",
        "start_date": "2023-11-15T08:00:00Z",
        "distance": 5000.0,
        "moving_time": 1800,
        "average_heartrate": None,
        "max_heartrate": None,
        "total_elevation_gain": 0,
        "average_watts": None,
        "max_watts": None,
        "device_name": None,
        "external_id": f"ext-{activity_id}",
    }

    try:
        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter([fake_activity])), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False), \
             patch("backend.services.strava_sync.get_activity_detail", return_value=fake_activity), \
             patch("backend.services.strava_sync.get_activity_streams", return_value={}):
            result = sync_strava_activities(user_id=uid)
        assert result["status"] == "completed"
        assert result["activities_created"] == 1

        reconcile_workouts(job_id=None, user_id=uid)  # must not raise

        # No stream row (empty streams)
        with engine.connect() as conn:
            wid = conn.execute(
                text("SELECT id FROM workouts WHERE user_id = :uid LIMIT 1"),
                {"uid": uid},
            ).scalar()
        if wid:
            assert _get_stream_row(str(wid)) is None
    finally:
        _drop_user(uid)


# ── AC2: Stryd sync integration ────────────────────────────────────────────────

def test_stryd_sync_stores_streams_payload_for_reconcile():
    """AC2: Stryd sync stores streams_payload in stryd_activities for reconcile."""
    from backend.services.stryd_sync import sync_stryd_activities

    uid = _make_user()
    activity_id = "stryd-ts-1700001000"
    streams = _stryd_streams_payload(duration_s=5, hz=1)
    streams["timestamp_list"] = [1_700_001_000 + i for i in range(5)]

    raw_act = {
        "id": activity_id,
        "name": "Stryd run",
        "timestamp": 1_700_001_000,
        "distance": 10000,
        "moving_time": 300,
        "average_power": 250,
        "average_heart_rate": 155,
        "stress": 80,
    }

    try:
        # Inject fake stryd credentials
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO stryd_credentials (user_id, athlete_id, stryd_email, stryd_password_encrypted) "
                    "VALUES (:uid, 'ath573', 'test@x.com', 'x') ON CONFLICT (user_id) DO NOTHING"
                ),
                {"uid": uid},
            )

        with patch("backend.services.stryd_sync.refresh_stryd_session_if_needed", return_value="fake-token"), \
             patch("backend.services.stryd_sync.fetch_stryd_activities", return_value=[raw_act]), \
             patch("backend.services.stryd_sync.fetch_stryd_activity_streams", return_value=streams):
            result = sync_stryd_activities(user_id=uid)

        assert result["upserted"] >= 1

        # Confirm streams_payload stored in stryd_activities
        with engine.connect() as conn:
            sp = conn.execute(
                text(
                    "SELECT streams_payload FROM stryd_activities "
                    "WHERE stryd_activity_id = :aid"
                ),
                {"aid": activity_id},
            ).scalar()
        assert sp is not None, "streams_payload should be stored in stryd_activities"
        assert "timestamp_list" in sp
    finally:
        _drop_user(uid)


def test_stryd_reconcile_writes_activity_streams():
    """AC2/AC9: After Stryd sync + reconcile, activity_streams row exists."""
    from backend.services.stryd_sync import sync_stryd_activities
    from backend.services.reconcile import reconcile_workouts

    uid = _make_user()
    activity_id = "stryd-ts-1700002000"
    streams = _stryd_streams_payload(duration_s=5, hz=1)
    streams["timestamp_list"] = [1_700_002_000 + i for i in range(5)]

    raw_act = {
        "id": activity_id,
        "name": "Stryd run 2",
        "timestamp": 1_700_002_000,
        "distance": 8000,
        "moving_time": 300,
        "average_power": 240,
        "average_heart_rate": 160,
        "stress": 70,
    }

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO stryd_credentials (user_id, athlete_id, stryd_email, stryd_password_encrypted) "
                    "VALUES (:uid, 'ath573b', 'test2@x.com', 'x') ON CONFLICT (user_id) DO NOTHING"
                ),
                {"uid": uid},
            )

        with patch("backend.services.stryd_sync.refresh_stryd_session_if_needed", return_value="fake-token"), \
             patch("backend.services.stryd_sync.fetch_stryd_activities", return_value=[raw_act]), \
             patch("backend.services.stryd_sync.fetch_stryd_activity_streams", return_value=streams):
            sync_stryd_activities(user_id=uid)

        reconcile_workouts(job_id=None, user_id=uid)

        with engine.connect() as conn:
            wid = conn.execute(
                text("SELECT id FROM workouts WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"),
                {"uid": uid},
            ).scalar()
        assert wid is not None

        stream_row = _get_stream_row(str(wid))
        assert stream_row is not None, "activity_streams row should exist after stryd reconcile"
        assert stream_row["source"] == "stryd"
        assert stream_row.get("heart_rate_bpm") is not None
    finally:
        _drop_user(uid)
