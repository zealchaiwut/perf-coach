"""Tests for issue #1295: Serve workout detail from downsampled activity_streams.

AC1 — Chart/stream data served from activity_streams table, not streams_payload.
AC2 — streams_payload is not decoded in Python when activity_streams row exists.
AC3 — compute_manual_laps no longer materialises full streams per request;
       laps are persisted in stryd_activities.manual_laps at sync-time.
AC4 — Response JSON shape of GET /api/workouts/{id}/full is unchanged.
AC5 — Fallback: workouts without activity_streams row still render correctly.
AC6 — detail endpoint emits no SQL selecting streams_payload when row exists;
       laps and summary fields match pre-change values.
"""
from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone


# ── AC1 + helper: activity_streams → Strava-format streams dict ───────────────


def test_activity_streams_to_strava_dict_maps_power():
    """AC1: power_w → watts channel in Strava format."""
    from backend.services.activity_streams import activity_streams_to_strava_dict
    row = types.SimpleNamespace(
        time_offset_seconds=[0, 1, 2],
        power_w=[200, 210, 205],
        heart_rate_bpm=None,
        pace_seconds_per_km=None,
        cadence_spm=None,
        altitude_m=None,
        latitude=None,
        longitude=None,
    )
    result = activity_streams_to_strava_dict(row)
    assert "watts" in result
    assert result["watts"]["data"] == [200, 210, 205]


def test_activity_streams_to_strava_dict_maps_heartrate():
    """AC1: heart_rate_bpm → heartrate channel."""
    from backend.services.activity_streams import activity_streams_to_strava_dict
    row = types.SimpleNamespace(
        time_offset_seconds=[0, 1, 2],
        power_w=None,
        heart_rate_bpm=[140, 142, 141],
        pace_seconds_per_km=None,
        cadence_spm=None,
        altitude_m=None,
        latitude=None,
        longitude=None,
    )
    result = activity_streams_to_strava_dict(row)
    assert "heartrate" in result
    assert result["heartrate"]["data"] == [140, 142, 141]


def test_activity_streams_to_strava_dict_converts_pace_to_velocity():
    """AC1: pace_seconds_per_km → velocity_smooth via 1000/pace."""
    from backend.services.activity_streams import activity_streams_to_strava_dict
    row = types.SimpleNamespace(
        time_offset_seconds=[0, 1],
        power_w=None,
        heart_rate_bpm=None,
        pace_seconds_per_km=[250.0, 300.0],  # 4:10/km and 5:00/km
        cadence_spm=None,
        altitude_m=None,
        latitude=None,
        longitude=None,
    )
    result = activity_streams_to_strava_dict(row)
    assert "velocity_smooth" in result
    vels = result["velocity_smooth"]["data"]
    assert len(vels) == 2
    assert abs(vels[0] - 4.0) < 0.01   # 1000/250 = 4.0 m/s
    assert abs(vels[1] - 3.333) < 0.01  # 1000/300 ≈ 3.333 m/s


def test_activity_streams_to_strava_dict_maps_latlng():
    """AC1: latitude/longitude → latlng as [[lat, lng], ...] pairs."""
    from backend.services.activity_streams import activity_streams_to_strava_dict
    row = types.SimpleNamespace(
        time_offset_seconds=[0, 1],
        power_w=None,
        heart_rate_bpm=None,
        pace_seconds_per_km=None,
        cadence_spm=None,
        altitude_m=None,
        latitude=[13.0, 13.1],
        longitude=[100.5, 100.6],
    )
    result = activity_streams_to_strava_dict(row)
    assert "latlng" in result
    assert result["latlng"]["data"] == [(13.0, 100.5), (13.1, 100.6)]


def test_activity_streams_to_strava_dict_skips_none_channels():
    """AC1: Channels with no data are omitted from the result dict."""
    from backend.services.activity_streams import activity_streams_to_strava_dict
    row = types.SimpleNamespace(
        time_offset_seconds=[0, 1],
        power_w=None,
        heart_rate_bpm=[140, 142],
        pace_seconds_per_km=None,
        cadence_spm=None,
        altitude_m=None,
        latitude=None,
        longitude=None,
    )
    result = activity_streams_to_strava_dict(row)
    assert "watts" not in result
    assert "heartrate" in result
    assert "velocity_smooth" not in result


# ── AC2: _strava_source_dict accepts prebuilt_streams ────────────────────────


def test_strava_source_dict_uses_prebuilt_streams_not_payload():
    """AC2: When prebuilt_streams provided, streams_payload is never accessed.

    We use a SimpleNamespace without a streams_payload attr — accessing it
    would raise AttributeError, proving the code path skips it.
    """
    from backend.main import _strava_source_dict

    sa = types.SimpleNamespace(
        strava_activity_id=1,
        name="Test Run",
        activity_type="Run",
        start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        distance_km=10.0,
        duration_seconds=3600,
        avg_hr=140,
        max_hr=165,
        elevation_m=50,
        avg_power_w=None,
        max_power_w=None,
        avg_cadence=None,
        suffer_score=None,
        device_name=None,
        external_id=None,
        is_stryd_synced=False,
        detail_payload={},
        raw_payload={},
        # No streams_payload attribute — access would crash
    )

    prebuilt = {"watts": {"data": [200, 210]}, "heartrate": {"data": [140, 142]}}
    result = _strava_source_dict(sa, prebuilt_streams=prebuilt)
    assert result is not None
    assert result["streams"] == prebuilt
    assert "watts" in result["stream_types"]


def test_strava_source_dict_falls_back_to_streams_payload_when_no_prebuilt():
    """AC5: Without prebuilt_streams, falls back to sa.streams_payload."""
    from backend.main import _strava_source_dict

    payload = {"heartrate": {"data": [130, 132]}}
    sa = types.SimpleNamespace(
        strava_activity_id=2,
        name="Fallback Run",
        activity_type="Run",
        start_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
        distance_km=5.0,
        duration_seconds=1800,
        avg_hr=130,
        max_hr=155,
        elevation_m=20,
        avg_power_w=None,
        max_power_w=None,
        avg_cadence=None,
        suffer_score=None,
        device_name=None,
        external_id=None,
        is_stryd_synced=False,
        detail_payload={},
        raw_payload={},
        streams_payload=payload,
    )

    result = _strava_source_dict(sa)
    assert result["streams"] == payload


# ── AC3: manual_laps column on StrydActivity ─────────────────────────────────


def test_stryd_activity_has_manual_laps_column():
    """AC3: StrydActivity model has a manual_laps column."""
    from sqlalchemy import inspect as sa_inspect
    from backend.models import StrydActivity
    mapper = sa_inspect(StrydActivity).mapper
    col_names = [c.key for c in mapper.column_attrs]
    assert "manual_laps" in col_names, (
        "StrydActivity must have a manual_laps column for persisted lap data"
    )


def test_stryd_activity_manual_laps_deferred():
    """AC3: manual_laps is deferred to avoid loading JSONB on every query."""
    from sqlalchemy import inspect as sa_inspect
    from backend.models import StrydActivity
    mapper = sa_inspect(StrydActivity).mapper
    prop = mapper.column_attrs.get("manual_laps")
    assert prop is not None and prop.deferred, (
        "StrydActivity.manual_laps must be deferred()"
    )


def test_stryd_source_dict_uses_manual_laps_when_available():
    """AC3: _stryd_source_dict reads manual_laps instead of streams_payload.

    No streams_payload attr on the namespace — accessing it would crash.
    """
    from backend.main import _stryd_source_dict

    expected_laps = [
        {"index": 1, "distance_km": 1.0, "duration_seconds": 240,
         "avg_hr": 145, "avg_power": 220, "cadence_spm": 170, "stride_length_m": 1.2},
    ]
    sta = types.SimpleNamespace(
        stryd_activity_id="abc123",
        name="Interval Run",
        start_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
        distance_km=5.0,
        duration_seconds=1800,
        avg_power_w=210,
        avg_hr=145,
        tss=80,
        form_metrics={"np_w": 230},
        power_zones={"z1": 300},
        splits=[],
        manual_laps=expected_laps,
        # No streams_payload — access would crash
    )

    result = _stryd_source_dict(sta)
    assert result is not None
    assert result["laps"] == expected_laps


def test_stryd_source_dict_falls_back_to_streams_payload_when_manual_laps_none():
    """AC5: When manual_laps is None, falls back to compute_manual_laps from streams_payload."""
    from backend.main import _stryd_source_dict

    # Streams with no lap markers → empty laps list
    streams = {
        "timestamp_list": [1700000000, 1700000001, 1700000002],
        "heart_rate_list": [145, 146, 147],
    }
    sta = types.SimpleNamespace(
        stryd_activity_id="xyz789",
        name="Easy Run",
        start_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
        distance_km=8.0,
        duration_seconds=2700,
        avg_power_w=200,
        avg_hr=140,
        tss=60,
        form_metrics={},
        power_zones={},
        splits=[],
        manual_laps=None,
        streams_payload=streams,
        raw_payload={},
    )

    result = _stryd_source_dict(sta)
    assert result is not None
    assert result["laps"] == []  # no lap markers → empty


# ── AC3: enrich_one persists manual_laps at sync time ────────────────────────


def test_enrich_one_computes_and_persists_manual_laps():
    """AC3: _enrich_one stores manual_laps in vals dict when streams have lap markers."""
    import importlib
    stryd_sync = importlib.import_module("backend.services.stryd_sync")

    base_ts = 1_700_000_000
    streams = {
        "timestamp_list": [base_ts, base_ts + 60, base_ts + 120, base_ts + 180,
                           base_ts + 240, base_ts + 300],
        "heart_rate_list": [145, 147, 148, 149, 150, 148],
        "total_power_list": [210, 215, 220, 218, 212, 208],
        "lap_timestamp_list": [base_ts + 150],  # one lap marker mid-stream
    }

    captured_vals = {}

    def mock_fetch(token, aid):
        return streams

    def mock_compute_km_splits(s):
        return []

    def mock_session_update(vals_dict, **_):
        captured_vals.update(vals_dict)

    import unittest.mock as mock
    with (
        mock.patch.object(stryd_sync, "fetch_stryd_activity_streams", side_effect=mock_fetch),
        mock.patch.object(stryd_sync, "compute_km_splits", side_effect=mock_compute_km_splits),
        mock.patch("backend.services.stryd_sync.Session") as mock_sess_cls,
    ):
        mock_sess = mock.MagicMock()
        mock_sess_cls.return_value.__enter__.return_value = mock_sess
        q = mock.MagicMock()
        q.filter.return_value = q
        q.update.side_effect = lambda vals, **kw: captured_vals.update(vals)
        mock_sess.query.return_value = q

        stryd_sync._enrich_one("tok", "act1")

    assert "manual_laps" in captured_vals, (
        "_enrich_one must persist manual_laps in the update dict"
    )
    laps = captured_vals["manual_laps"]
    assert isinstance(laps, list)
    assert len(laps) >= 1


# ── AC4: response shape unchanged ────────────────────────────────────────────


def test_strava_source_dict_shape_preserved_with_prebuilt_streams():
    """AC4: Response includes all expected keys when prebuilt_streams is used."""
    from backend.main import _strava_source_dict

    sa = types.SimpleNamespace(
        strava_activity_id=99,
        name="Shape Test",
        activity_type="Run",
        start_time=datetime(2024, 5, 1, tzinfo=timezone.utc),
        distance_km=12.0,
        duration_seconds=4000,
        avg_hr=142,
        max_hr=168,
        elevation_m=100,
        avg_power_w=None,
        max_power_w=None,
        avg_cadence=None,
        suffer_score=None,
        device_name=None,
        external_id=None,
        is_stryd_synced=False,
        detail_payload={
            "laps": [{"lap_index": 1}],
            "splits_metric": [],
            "best_efforts": [],
            "segment_efforts": [],
            "calories": 500,
            "description": None,
            "gear": None,
            "map": {"polyline": "abc"},
        },
        raw_payload={},
    )

    prebuilt = {"heartrate": {"data": [140, 142]}}
    result = _strava_source_dict(sa, prebuilt_streams=prebuilt)

    expected_keys = {
        "strava_activity_id", "name", "activity_type", "start_time",
        "distance_km", "duration_seconds", "avg_hr", "max_hr", "elevation_m",
        "laps", "splits_metric", "best_efforts", "segment_efforts",
        "calories", "description", "gear", "map_polyline",
        "stream_types", "streams",
    }
    missing = expected_keys - set(result.keys())
    assert not missing, f"Missing keys in _strava_source_dict result: {missing}"
    assert result["laps"] == [{"lap_index": 1}]
    assert result["calories"] == 500


# ── AC6: SQL probe — streams_payload not selected ────────────────────────────


def test_strava_source_dict_compiled_sql_omits_streams_payload():
    """AC6: The compiled ORM query for the detail endpoint omits streams_payload.

    StravaActivity.streams_payload is deferred, so it should not appear in
    the default SELECT compiled SQL.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql as pg
    from backend.models import StravaActivity

    stmt = select(StravaActivity)
    sql = str(stmt.compile(dialect=pg.dialect()))
    assert "streams_payload" not in sql, (
        "streams_payload must be deferred and absent from default StravaActivity SELECT"
    )


def test_stryd_activity_compiled_sql_omits_streams_payload():
    """AC6: Default StrydActivity SELECT omits streams_payload (deferred)."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql as pg
    from backend.models import StrydActivity

    stmt = select(StrydActivity)
    sql = str(stmt.compile(dialect=pg.dialect()))
    assert "streams_payload" not in sql, (
        "streams_payload must be deferred and absent from default StrydActivity SELECT"
    )


def test_stryd_activity_compiled_sql_omits_manual_laps():
    """AC3/AC6: manual_laps is deferred — not loaded on every StrydActivity SELECT."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql as pg
    from backend.models import StrydActivity

    stmt = select(StrydActivity)
    sql = str(stmt.compile(dialect=pg.dialect()))
    assert "manual_laps" not in sql, (
        "manual_laps must be deferred and absent from default StrydActivity SELECT"
    )


# ── AC6: laps/summary field parity ───────────────────────────────────────────


def test_stryd_source_dict_laps_field_present_from_manual_laps():
    """AC6: laps field populated correctly from persisted manual_laps."""
    from backend.main import _stryd_source_dict

    laps = [
        {"index": 1, "distance_km": 1.0, "duration_seconds": 240,
         "avg_hr": 145, "avg_power": 220, "cadence_spm": 170, "stride_length_m": 1.2},
        {"index": 2, "distance_km": 1.0, "duration_seconds": 235,
         "avg_hr": 147, "avg_power": 225, "cadence_spm": 172, "stride_length_m": 1.22},
    ]
    sta = types.SimpleNamespace(
        stryd_activity_id="lap_test",
        name="2-lap run",
        start_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
        distance_km=2.0,
        duration_seconds=475,
        avg_power_w=222,
        avg_hr=146,
        tss=40,
        form_metrics={},
        power_zones={},
        splits=[],
        manual_laps=laps,
    )

    result = _stryd_source_dict(sta)
    assert result["laps"] == laps


def test_migration_adds_manual_laps_column():
    """AC3: Alembic migration file exists for manual_laps on stryd_activities."""
    import pathlib
    versions_dir = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*.py"))
    content = "\n".join(f.read_text() for f in migration_files)
    assert "manual_laps" in content, (
        "No Alembic migration found that adds manual_laps to stryd_activities"
    )
    assert "stryd_activities" in content
