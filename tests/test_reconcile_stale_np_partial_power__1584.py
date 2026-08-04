"""Tests for issue #1584: stale workout.np survives when NP compute returns None on partial power data.

Acceptance criteria covered:
  AC-partial-strava  — strava re-sync with power samples present but insufficient
                       (< 30 s) clears stale workout.np to None
  AC-partial-stryd   — stryd re-sync with power samples present but insufficient
                       clears stale workout.np to None
  AC-no-regression   — re-sync with sufficient power samples still sets workout.np
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.services.reconcile import _ingest_streams

# fewer than 30 samples → compute_normalized_power returns (None, reason)
_FEW = 10


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


def _strava_payload_with_few_power_samples(n=_FEW, watts=250):
    time_data = list(range(n))
    return {
        "time": {"data": time_data, "series_type": "time", "original_size": n},
        "watts": {"data": [watts] * n, "series_type": "time", "original_size": n},
    }


def _stryd_payload_with_few_power_samples(n=_FEW, watts=300):
    base_ts = 1700000000000
    ts_list = [base_ts + i * 1000 for i in range(n)]
    return {
        "timestamp_list": ts_list,
        "total_power_list": [float(watts)] * n,
    }


# ── AC-partial-strava ─────────────────────────────────────────────────────────

def test_strava_partial_power_clears_stale_np():
    """AC-partial-strava: strava re-sync has power samples but too few for NP
    computation; stale workout.np must be cleared to None."""
    workout = _make_workout(np_val=280)
    assert workout.np == 280

    act = _make_strava_act(workout, _strava_payload_with_few_power_samples())
    session = _make_session()

    with patch("backend.services.activity_streams.write_activity_stream"):
        _ingest_streams(session, [("strava", act)], [workout])

    assert workout.np is None, (
        "workout.np must be cleared to None when power stream has insufficient samples for NP"
    )


# ── AC-partial-stryd ──────────────────────────────────────────────────────────

def test_stryd_partial_power_clears_stale_np():
    """AC-partial-stryd: stryd re-sync has power samples but too few for NP
    computation; stale workout.np must be cleared to None."""
    workout = _make_workout(np_val=310)
    assert workout.np == 310

    act = _make_stryd_act(workout, _stryd_payload_with_few_power_samples())
    session = _make_session()

    with patch("backend.services.activity_streams.write_activity_stream"):
        _ingest_streams(session, [("stryd", act)], [workout])

    assert workout.np is None, (
        "workout.np must be cleared to None when stryd power stream has insufficient samples for NP"
    )


# ── AC-no-regression ─────────────────────────────────────────────────────────

def test_strava_sufficient_power_still_sets_np():
    """AC-no-regression: re-sync with 120 power samples (> 30 window) still sets np."""
    workout = _make_workout(np_val=None)

    n = 120
    time_data = list(range(n))
    payload = {
        "time": {"data": time_data, "series_type": "time", "original_size": n},
        "watts": {"data": [250] * n, "series_type": "time", "original_size": n},
    }
    act = _make_strava_act(workout, payload)
    session = _make_session()

    with patch("backend.services.activity_streams.write_activity_stream"):
        _ingest_streams(session, [("strava", act)], [workout])

    assert workout.np == 250, "workout.np must still be computed when power stream is sufficient"
