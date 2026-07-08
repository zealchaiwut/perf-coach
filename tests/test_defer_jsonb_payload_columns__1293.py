"""Tests for issue #1293: JSONB payload columns mapped deferred() in models.py.

AC coverage:
  AC1 — StravaActivity.raw_payload, detail_payload, streams_payload are deferred
  AC2 — StrydActivity.raw_payload, streams_payload, splits, form_metrics are deferred
  AC3 — ActivityStream JSONB channel columns are deferred (or explicitly documented)
  AC4 — List query SQL does NOT include streams_payload (deferred not selected eagerly)
  AC5 — Detail serialiser helpers (_strava_source_dict, _stryd_source_dict) still
         access payload columns without error when given an in-memory object (session
         lazy-load path is exercised by UAT; here we verify the helpers don't crash)
  AC6 — Existing explicit defer() options in reconcile.py remain valid — no error
         when the query option is applied to an already-deferred column
  AC7 — No DetachedInstanceError risk: deferred columns on a model instance can be
         read when the instance has the attribute populated manually (i.e. session
         close does not corrupt set values)
  AC8 — Workouts list compiled SQL omits payload columns; verifiable via
         SQLAlchemy ORM query compilation
"""

from __future__ import annotations

import types

import pytest
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import ColumnProperty


# ── helpers ──────────────────────────────────────────────────────────────────


def _is_deferred(model_cls, attr_name: str) -> bool:
    """Return True if the named column attribute is mapped deferred()."""
    mapper = sa_inspect(model_cls).mapper
    prop = mapper.column_attrs.get(attr_name)
    if prop is None:
        raise AttributeError(f"{model_cls.__name__} has no column attr '{attr_name}'")
    return prop.deferred


# ── AC1: StravaActivity payload columns are deferred ─────────────────────────


def test_strava_raw_payload_deferred():
    """AC1: StravaActivity.raw_payload is mapped deferred()."""
    from backend.models import StravaActivity
    assert _is_deferred(StravaActivity, "raw_payload"), (
        "StravaActivity.raw_payload must be deferred()"
    )


def test_strava_detail_payload_deferred():
    """AC1: StravaActivity.detail_payload is mapped deferred()."""
    from backend.models import StravaActivity
    assert _is_deferred(StravaActivity, "detail_payload"), (
        "StravaActivity.detail_payload must be deferred()"
    )


def test_strava_streams_payload_deferred():
    """AC1: StravaActivity.streams_payload is mapped deferred()."""
    from backend.models import StravaActivity
    assert _is_deferred(StravaActivity, "streams_payload"), (
        "StravaActivity.streams_payload must be deferred()"
    )


# ── AC2: StrydActivity payload columns are deferred ──────────────────────────


def test_stryd_raw_payload_deferred():
    """AC2: StrydActivity.raw_payload is mapped deferred()."""
    from backend.models import StrydActivity
    assert _is_deferred(StrydActivity, "raw_payload"), (
        "StrydActivity.raw_payload must be deferred()"
    )


def test_stryd_streams_payload_deferred():
    """AC2: StrydActivity.streams_payload is mapped deferred()."""
    from backend.models import StrydActivity
    assert _is_deferred(StrydActivity, "streams_payload"), (
        "StrydActivity.streams_payload must be deferred()"
    )


def test_stryd_splits_deferred():
    """AC2: StrydActivity.splits is mapped deferred()."""
    from backend.models import StrydActivity
    assert _is_deferred(StrydActivity, "splits"), (
        "StrydActivity.splits must be deferred()"
    )


def test_stryd_form_metrics_deferred():
    """AC2: StrydActivity.form_metrics is mapped deferred()."""
    from backend.models import StrydActivity
    assert _is_deferred(StrydActivity, "form_metrics"), (
        "StrydActivity.form_metrics must be deferred()"
    )


# ── AC3: ActivityStream channel columns reviewed ─────────────────────────────


def test_activity_stream_channel_columns_deferred():
    """AC3: ActivityStream per-sample JSONB channels are deferred (not bulk-loaded).

    These are the large array columns; deferring them prevents multi-MB loads
    on any query that joins or bulk-loads ActivityStream rows.
    """
    from backend.models import ActivityStream
    channel_cols = [
        "time_offset_seconds",
        "power_w",
        "heart_rate_bpm",
        "pace_seconds_per_km",
        "cadence_spm",
        "altitude_m",
        "latitude",
        "longitude",
        "channel_attribution",
    ]
    not_deferred = [c for c in channel_cols if not _is_deferred(ActivityStream, c)]
    assert not not_deferred, (
        f"ActivityStream channel columns not deferred: {not_deferred}"
    )


# ── AC4/AC8: List query compiled SQL omits payload columns ───────────────────


def test_strava_activity_select_omits_streams_payload():
    """AC4/AC8: ORM select(StravaActivity) SQL excludes streams_payload."""
    from backend.models import StravaActivity
    stmt = select(StravaActivity)
    sql = str(stmt.compile(dialect=pg.dialect()))
    assert "streams_payload" not in sql, (
        "streams_payload must not appear in a default SELECT for StravaActivity "
        "(deferred columns are omitted from the generated SQL)"
    )


def test_strava_activity_select_omits_raw_payload():
    """AC4/AC8: ORM select(StravaActivity) SQL excludes raw_payload."""
    from backend.models import StravaActivity
    stmt = select(StravaActivity)
    sql = str(stmt.compile(dialect=pg.dialect()))
    assert "raw_payload" not in sql, (
        "raw_payload must not appear in default SELECT for StravaActivity"
    )


def test_stryd_activity_select_omits_streams_payload():
    """AC4/AC8: ORM select(StrydActivity) SQL excludes streams_payload."""
    from backend.models import StrydActivity
    stmt = select(StrydActivity)
    sql = str(stmt.compile(dialect=pg.dialect()))
    assert "streams_payload" not in sql, (
        "streams_payload must not appear in default SELECT for StrydActivity"
    )


def test_stryd_activity_select_omits_form_metrics():
    """AC4/AC8: ORM select(StrydActivity) SQL excludes form_metrics."""
    from backend.models import StrydActivity
    stmt = select(StrydActivity)
    sql = str(stmt.compile(dialect=pg.dialect()))
    assert "form_metrics" not in sql, (
        "form_metrics must not appear in default SELECT for StrydActivity"
    )


# ── AC5: Detail serialisers accept pre-populated objects without crashing ─────


def test_strava_source_dict_accepts_populated_object():
    """AC5: _strava_source_dict returns a dict when given a fully populated object.

    Simulates the detail-view path where payload columns are already loaded
    (either lazy-loaded within the session or pre-populated in tests).
    """
    from backend.main import _strava_source_dict
    import uuid
    from datetime import datetime, timezone

    act = types.SimpleNamespace(
        strava_activity_id=12345,
        name="Test Run",
        activity_type="Run",
        start_time=datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc),
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
        detail_payload={"laps": [{"distance": 1000}], "splits_metric": []},
        streams_payload={"heartrate": {"data": [140, 141, 142]}},
        raw_payload={"id": 12345, "map": {"summary_polyline": "abc"}},
    )
    result = _strava_source_dict(act)
    assert isinstance(result, dict)
    assert result["strava_activity_id"] == 12345
    assert result["laps"] == [{"distance": 1000}]
    assert "heartrate" in result["streams"]


def test_stryd_source_dict_accepts_populated_object():
    """AC5: _stryd_source_dict returns a dict when given a fully populated object."""
    from backend.main import _stryd_source_dict
    from datetime import datetime, timezone

    act = types.SimpleNamespace(
        stryd_activity_id="stryd-abc",
        name="Test Run",
        start_time=datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc),
        distance_km=10.0,
        duration_seconds=3600,
        avg_power_w=250,
        avg_hr=140,
        tss=80,
        form_metrics={"max_power_w": 400, "np_w": 260},
        power_zones={"z1": 10, "z2": 40},
        splits=[{"distance_km": 1.0, "pace_seconds_per_km": 360}],
        streams_payload={
            "time": {"data": [0, 1, 2]},
            "power": {"data": [250, 260, 255]},
            "lap_triggers": [],
        },
        raw_payload={"laps": []},
    )
    result = _stryd_source_dict(act)
    assert isinstance(result, dict)
    assert result["stryd_activity_id"] == "stryd-abc"
    assert result["form_metrics"]["max_power_w"] == 400


# ── AC6: Existing explicit defer() query options don't error on deferred cols ─


def test_reconcile_defer_options_are_valid():
    """AC6: Applying explicit defer() on already-deferred columns doesn't raise.

    reconcile.py uses explicit _defer(StravaActivity.streams_payload) query
    options. With model-level deferred(), the option is redundant but harmless —
    SQLAlchemy silently applies it again without error.
    """
    from sqlalchemy.orm import defer as orm_defer
    from backend.models import StravaActivity, StrydActivity

    # These should not raise AttributeError or any other exception
    opt1 = orm_defer(StravaActivity.streams_payload)
    opt2 = orm_defer(StravaActivity.detail_payload)
    opt3 = orm_defer(StrydActivity.streams_payload)
    assert opt1 is not None
    assert opt2 is not None
    assert opt3 is not None


# ── AC7: Deferred columns accessed outside session via pre-set attribute ──────


def test_deferred_column_readable_when_pre_populated():
    """AC7: A deferred column value set before session expiry is still readable.

    This simulates the pattern in _strava_source_dict / _stryd_source_dict where
    the calling code is inside a 'with Session(engine)' block — lazy-load fires
    within the session, value is stored, and the dict is built before the session
    closes. The test verifies the serialiser helpers read the value correctly.
    """
    from backend.main import _strava_source_dict
    from datetime import datetime, timezone

    # Simulate a loaded StravaActivity-like object with all payload cols set
    act = types.SimpleNamespace(
        strava_activity_id=99,
        name="Run",
        activity_type="Run",
        start_time=datetime(2024, 3, 15, tzinfo=timezone.utc),
        distance_km=5.0,
        duration_seconds=1800,
        avg_hr=None,
        max_hr=None,
        elevation_m=None,
        avg_power_w=None,
        max_power_w=None,
        avg_cadence=None,
        suffer_score=None,
        device_name=None,
        external_id=None,
        is_stryd_synced=False,
        detail_payload=None,
        streams_payload=None,
        raw_payload={},
    )
    # None payloads should be handled gracefully (not raise)
    result = _strava_source_dict(act)
    assert result["laps"] == []
    assert result["streams"] == {}
