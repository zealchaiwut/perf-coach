"""Tests for issue #667: Ingest activity streams on Strava and Stryd sync.

Each test is anchored to a specific acceptance criterion (AC) from the issue.
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
)
from backend.services.reconcile import write_activity_stream


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user() -> str:
    name = f"as667_{uuid.uuid4().hex[:8]}"
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


def _strava_payload(duration_s: int = 5, hz: int = 1) -> dict:
    n = duration_s * hz
    step = 1.0 / hz
    return {
        "time": {"data": [round(i * step, 4) for i in range(n)]},
        "heartrate": {"data": [140 + (i % 20) for i in range(n)]},
        "altitude": {"data": [100.0 + i * 0.1 for i in range(n)]},
        "cadence": {"data": [80 + (i % 5) for i in range(n)]},
        "velocity_smooth": {"data": [3.5 + (i % 5) * 0.1 for i in range(n)]},
    }


def _stryd_payload(duration_s: int = 5, hz: int = 1) -> dict:
    n = duration_s * hz
    step = 1.0 / hz
    base_ts = 1_700_000_000
    return {
        "timestamp_list": [base_ts + i * step for i in range(n)],
        "heart_rate_list": [150 + (i % 10) for i in range(n)],
        "total_power_list": [200 + (i % 30) for i in range(n)],
        "cadence_list": [170 + (i % 5) for i in range(n)],
        "speed_list": [3.0 + (i % 5) * 0.1 for i in range(n)],
    }


# ── AC11: 10 Hz → 1 Hz downsampling (explicitly required by AC11) ─────────────

def test_downsample_10hz_to_1hz():
    """AC11: downsampling reduces a 10 Hz series to 1 Hz (at most one sample/second)."""
    duration_s = 5
    hz = 10
    n = duration_s * hz
    timestamps = [round(i * 0.1, 4) for i in range(n)]
    values = list(range(n))
    result = downsample_to_1hz(timestamps, values)
    # Should produce exactly `duration_s` samples — one per second bucket
    assert len(result) == duration_s
    buckets = [r[0] for r in result]
    assert buckets == list(range(duration_s))
    # First-sample-in-window: bucket 0 → value 0, bucket 1 → value 10, etc.
    assert result[0][1] == 0.0
    assert result[1][1] == 10.0
    assert result[2][1] == 20.0


def test_downsample_10hz_strava_payload():
    """AC3/AC11: 10 Hz Strava payload stored at ≤1 sample/second."""
    payload = _strava_payload(duration_s=6, hz=10)
    row, err = extract_strava_streams(payload)
    assert err is None
    hr = row.get("heart_rate_bpm") or []
    assert len(hr) <= 6, f"Expected ≤6 samples after 10 Hz → 1 Hz, got {len(hr)}"


def test_downsample_10hz_stryd_payload():
    """AC3/AC11: 10 Hz Stryd payload stored at ≤1 sample/second."""
    payload = _stryd_payload(duration_s=6, hz=10)
    row, err = extract_stryd_streams(payload)
    assert err is None
    hr = row.get("heart_rate_bpm") or []
    assert len(hr) <= 6, f"Expected ≤6 samples after 10 Hz → 1 Hz, got {len(hr)}"


# ── AC8/AC11: missing channel returns null + reason ───────────────────────────

def test_strava_missing_time_stream_returns_null_with_reason():
    """AC8/AC11: Missing time stream → null + human-readable reason."""
    payload = {"heartrate": {"data": [140, 141, 142]}}
    row, reason = extract_strava_streams(payload)
    assert row is None
    assert reason is not None and len(reason) > 0
    assert "time" in reason.lower()


def test_stryd_missing_timestamp_list_returns_null_with_reason():
    """AC8/AC11: Missing timestamp_list → null + reason."""
    payload = {"heart_rate_list": [150, 151, 152]}
    row, reason = extract_stryd_streams(payload)
    assert row is None
    assert reason is not None and len(reason) > 0
    assert "timestamp" in reason.lower()


def test_strava_none_payload_returns_null_with_reason():
    """AC8: None payload → null + reason."""
    row, reason = extract_strava_streams(None)
    assert row is None
    assert reason is not None


def test_stryd_none_payload_returns_null_with_reason():
    """AC8: None payload → null + reason."""
    row, reason = extract_stryd_streams(None)
    assert row is None
    assert reason is not None


# ── AC5/AC11: bad channel does not prevent other channels ────────────────────

def test_strava_bad_channel_data_does_not_abort_others():
    """AC5/AC11: A single channel with invalid (non-iterable) data is skipped;
    other channels are still extracted successfully."""
    payload = {
        "time": {"data": [0, 1, 2, 3, 4]},
        "heartrate": {"data": [140, 141, 142, 143, 144]},
        # cadence channel has bad data (a scalar instead of a list)
        "cadence": {"data": 99},
        "altitude": {"data": [100.0, 100.1, 100.2, 100.3, 100.4]},
    }
    row, err = extract_strava_streams(payload)
    # Extraction must succeed (not raise, not return None)
    assert row is not None, f"Expected successful extraction; got err={err!r}"
    assert err is None
    # heartrate and altitude should be present
    assert "heart_rate_bpm" in row
    assert "altitude_m" in row
    # cadence was bad — it should be absent, not raise
    assert "cadence_spm" not in row


def test_stryd_bad_channel_data_does_not_abort_others():
    """AC5/AC11: A Stryd channel with bad data is skipped; others continue."""
    base_ts = 1_700_000_000
    payload = {
        "timestamp_list": [base_ts + i for i in range(5)],
        "heart_rate_list": [150, 151, 152, 153, 154],
        # total_power_list has a bad value type (a dict instead of a list)
        "total_power_list": {"bad": "data"},
        "cadence_list": [170, 171, 172, 173, 174],
    }
    row, err = extract_stryd_streams(payload)
    assert row is not None, f"Expected successful extraction; got err={err!r}"
    assert err is None
    assert "heart_rate_bpm" in row
    assert "cadence_spm" in row
    # power should be absent (bad data), not crash
    assert "power_w" not in row


# ── AC4: Only returned channels are written ───────────────────────────────────

def test_strava_absent_channel_produces_no_row():
    """AC4: Channel not in the source response → no column in the output row."""
    payload = {
        "time": {"data": [0, 1, 2]},
        "heartrate": {"data": [140, 141, 142]},
        # No watts/power, cadence, altitude, latlng, velocity_smooth
    }
    row, err = extract_strava_streams(payload)
    assert err is None
    assert "power_w" not in row
    assert "cadence_spm" not in row
    assert "altitude_m" not in row
    assert "latitude" not in row
    assert "longitude" not in row
    assert "pace_seconds_per_km" not in row


def test_stryd_absent_channel_produces_no_column():
    """AC4: Channel absent from Stryd response produces no column."""
    payload = {
        "timestamp_list": [1_700_000_000 + i for i in range(3)],
        "heart_rate_list": [150, 151, 152],
        # No power, cadence, speed
    }
    row, err = extract_stryd_streams(payload)
    assert err is None
    assert "power_w" not in row
    assert "cadence_spm" not in row
    assert "pace_seconds_per_km" not in row


# ── AC6: source field recorded ────────────────────────────────────────────────

def test_strava_stream_row_records_source_strava():
    """AC6: Written row has source='strava'."""
    payload = _strava_payload(duration_s=3)
    row, err = extract_strava_streams(payload, source="strava")
    assert err is None
    assert row["source"] == "strava"


def test_stryd_stream_row_records_source_stryd():
    """AC6: Written row has source='stryd'."""
    payload = _stryd_payload(duration_s=3)
    row, err = extract_stryd_streams(payload, source="stryd")
    assert err is None
    assert row["source"] == "stryd"


# ── AC7: pure-function separation (no top-level DB imports) ──────────────────

def test_activity_streams_module_has_no_top_level_db_imports():
    """AC7: activity_streams module is pure — no top-level DB/session imports."""
    import ast
    import pathlib
    src = pathlib.Path("backend/services/activity_streams.py").read_text()
    tree = ast.parse(src)
    top_level = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom)) and n.col_offset == 0
    ]
    db_imports = [
        n for n in top_level
        if ("db" in (getattr(n, "module", "") or "")
            or any("db" in alias.name for alias in getattr(n, "names", [])))
    ]
    assert not db_imports, f"Top-level DB imports found: {db_imports}"


# ── AC9: no hardcoded numeric thresholds ─────────────────────────────────────

def test_no_hardcoded_sample_rate_limits():
    """AC9: No numeric thresholds are hardcoded in activity_streams module."""
    import inspect
    import backend.services.activity_streams as mod
    src = inspect.getsource(mod)
    for forbidden in ("max_hz =", "max_samples =", "min_pace =", "max_pace =", "max_hr ="):
        assert forbidden not in src, f"Hardcoded threshold found: {forbidden!r}"


# ── AC10: no merge logic — sources coexist independently ─────────────────────

def test_strava_and_stryd_streams_coexist_independently():
    """AC10: Strava and Stryd rows do NOT overwrite each other (written to separate workouts)."""
    uid = _make_user()
    try:
        wid_strava = _make_workout(uid)
        wid_stryd = _make_workout(uid)

        strava_row = {
            "source": "strava",
            "sample_interval_seconds": 1,
            "heart_rate_bpm": [140, 141, 142],
        }
        stryd_row = {
            "source": "stryd",
            "sample_interval_seconds": 1,
            "heart_rate_bpm": [160, 161, 162],
            "power_w": [250, 255, 260],
        }

        with Session(engine) as session:
            write_activity_stream(wid_strava, strava_row, session)
            write_activity_stream(wid_stryd, stryd_row, session)
            session.commit()

        stored_strava = _get_stream_row(wid_strava)
        stored_stryd = _get_stream_row(wid_stryd)

        assert stored_strava is not None
        assert stored_stryd is not None
        assert stored_strava["source"] == "strava"
        assert stored_stryd["source"] == "stryd"
        # Strava row has no power (wasn't written)
        assert stored_strava.get("power_w") is None
        # Stryd row has power
        assert stored_stryd["power_w"] == [250, 255, 260]
    finally:
        _drop_user(uid)


# ── AC1: Strava sync + reconcile integration ─────────────────────────────────

def test_strava_sync_and_reconcile_writes_activity_streams_667():
    """AC1: Strava activity sync followed by reconcile writes activity_streams rows."""
    from backend.services.strava_sync import sync_strava_activities
    from backend.services.reconcile import reconcile_workouts

    uid = _make_user()
    activity_id = 9_991_667
    streams = _strava_payload(duration_s=5, hz=1)

    fake_activity = {
        "id": activity_id,
        "name": "Issue 667 test run",
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
        with patch("backend.services.strava_sync.get_athlete_activities", return_value=iter([fake_activity])), \
             patch("backend.services.strava_sync.detect_stryd_origin", return_value=False), \
             patch("backend.services.strava_sync.get_activity_detail", return_value=fake_activity), \
             patch("backend.services.strava_sync.get_activity_streams", return_value=streams):
            result = sync_strava_activities(user_id=uid)
        assert result["status"] == "completed"

        reconcile_workouts(job_id=None, user_id=uid)

        with engine.connect() as conn:
            wid = conn.execute(
                text("SELECT id FROM workouts WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"),
                {"uid": uid},
            ).scalar()
        assert wid is not None

        stream_row = _get_stream_row(str(wid))
        assert stream_row is not None, "activity_streams row must exist after Strava reconcile"
        assert stream_row["source"] == "strava"
        assert stream_row.get("heart_rate_bpm") is not None
    finally:
        _drop_user(uid)


# ── AC2: Stryd sync + reconcile integration ──────────────────────────────────

def test_stryd_sync_and_reconcile_writes_activity_streams_667():
    """AC2: Stryd activity sync followed by reconcile writes activity_streams rows."""
    from backend.services.stryd_sync import sync_stryd_activities
    from backend.services.reconcile import reconcile_workouts

    uid = _make_user()
    activity_id = "stryd-ts-1700667000"
    streams = _stryd_payload(duration_s=5, hz=1)
    streams["timestamp_list"] = [1_700_667_000 + i for i in range(5)]

    raw_act = {
        "id": activity_id,
        "name": "Issue 667 Stryd run",
        "timestamp": 1_700_667_000,
        "distance": 10000,
        "moving_time": 300,
        "average_power": 250,
        "average_heart_rate": 155,
        "stress": 80,
    }

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO stryd_credentials (user_id, athlete_id, stryd_email, stryd_password_encrypted) "
                    "VALUES (:uid, 'ath667', 'test667@x.com', 'x') ON CONFLICT (user_id) DO NOTHING"
                ),
                {"uid": uid},
            )

        with patch("backend.services.stryd_sync.refresh_stryd_session_if_needed", return_value="fake-token"), \
             patch("backend.services.stryd_sync.fetch_stryd_activities", return_value=[raw_act]), \
             patch("backend.services.stryd_sync.fetch_stryd_activity_streams", return_value=streams):
            result = sync_stryd_activities(user_id=uid)
        assert result["upserted"] >= 1

        reconcile_workouts(job_id=None, user_id=uid)

        with engine.connect() as conn:
            wid = conn.execute(
                text("SELECT id FROM workouts WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"),
                {"uid": uid},
            ).scalar()
        assert wid is not None

        stream_row = _get_stream_row(str(wid))
        assert stream_row is not None, "activity_streams row must exist after Stryd reconcile"
        assert stream_row["source"] == "stryd"
        assert stream_row.get("heart_rate_bpm") is not None
    finally:
        _drop_user(uid)
