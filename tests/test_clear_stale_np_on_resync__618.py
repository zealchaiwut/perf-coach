"""Tests for issue #618: Clear workout.np when re-syncing an activity with no power stream.

Acceptance criteria covered:
  AC-resync-strava  — strava re-sync without power stream clears stale workout.np to None
  AC-resync-stryd   — stryd re-sync without power stream clears stale workout.np to None
  AC-power-retained — re-sync with power stream still sets workout.np (no regression)
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.services.reconcile import _ingest_streams


def _make_workout(np_val=None):
    w = SimpleNamespace(
        id=uuid.uuid4(),
        strava_activity_pk=None,
        stryd_activity_pk=None,
        np=np_val,
    )
    return w


def _make_strava_act(workout, streams_payload):
    act = MagicMock()
    act.id = workout.strava_activity_pk = uuid.uuid4()
    act.streams_payload = streams_payload
    return act


def _make_stryd_act(workout, streams_payload):
    act = MagicMock()
    act.id = workout.stryd_activity_pk = uuid.uuid4()
    act.streams_payload = streams_payload
    return act


def _make_session():
    s = MagicMock()
    s.execute = MagicMock()
    return s


def _strava_payload_with_power(n_seconds=120, watts=250):
    time_data = list(range(n_seconds))
    return {
        "time": {"data": time_data, "series_type": "time", "original_size": n_seconds},
        "watts": {"data": [watts] * n_seconds, "series_type": "time", "original_size": n_seconds},
    }


def _strava_payload_without_power(n_seconds=120):
    time_data = list(range(n_seconds))
    return {
        "time": {"data": time_data, "series_type": "time", "original_size": n_seconds},
        "heartrate": {"data": [140] * n_seconds, "series_type": "time", "original_size": n_seconds},
    }


def _stryd_payload_with_power(n_seconds=120, watts=300):
    base_ts = 1700000000000
    ts_list = [base_ts + i * 1000 for i in range(n_seconds)]
    return {
        "timestamp_list": ts_list,
        "total_power_list": [float(watts)] * n_seconds,
    }


def _stryd_payload_without_power(n_seconds=120):
    base_ts = 1700000000000
    ts_list = [base_ts + i * 1000 for i in range(n_seconds)]
    return {
        "timestamp_list": ts_list,
        "heart_rate_list": [140] * n_seconds,
    }


# ── AC-resync-strava ─────────────────────────────────────────────────────────

def test_strava_resync_without_power_clears_stale_np():
    """AC-resync-strava: workout previously had np set; re-sync with no power
    stream must clear workout.np to None rather than retaining the stale value."""
    workout = _make_workout(np_val=280)  # stale NP from a prior power-stream sync
    assert workout.np == 280

    act = _make_strava_act(workout, _strava_payload_without_power(n_seconds=120))
    session = _make_session()

    with patch("backend.services.reconcile.write_activity_stream"):
        _ingest_streams(session, [("strava", act)], [workout])

    assert workout.np is None, (
        "workout.np must be cleared to None when the re-synced activity has no power stream"
    )


# ── AC-resync-stryd ──────────────────────────────────────────────────────────

def test_stryd_resync_without_power_clears_stale_np():
    """AC-resync-stryd: workout previously had np set; re-sync from stryd with no
    power channel must clear workout.np to None."""
    workout = _make_workout(np_val=310)  # stale NP
    assert workout.np == 310

    act = _make_stryd_act(workout, _stryd_payload_without_power(n_seconds=120))
    session = _make_session()

    with patch("backend.services.reconcile.write_activity_stream"):
        _ingest_streams(session, [("stryd", act)], [workout])

    assert workout.np is None, (
        "workout.np must be cleared to None when the re-synced stryd activity has no power stream"
    )


# ── AC-power-retained (no regression) ───────────────────────────────────────

def test_strava_resync_with_power_retains_np():
    """AC-power-retained: re-sync that includes a power stream still sets workout.np."""
    workout = _make_workout(np_val=None)
    act = _make_strava_act(workout, _strava_payload_with_power(n_seconds=120, watts=250))
    session = _make_session()

    with patch("backend.services.reconcile.write_activity_stream"):
        _ingest_streams(session, [("strava", act)], [workout])

    assert workout.np == 250, "workout.np must still be computed from the power stream"
