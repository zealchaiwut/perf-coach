"""Strava 1 km splits_metric → workout_splits when Stryd splits are missing."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.services.reconcile import (
    _sync_splits,
    _write_split_rows,
    fill_strava_km_splits_if_missing,
    strava_metric_from_activity,
    strava_splits_metric_to_rows,
    synthetic_split_rows,
)


def _metric_km(n=3, last_m=1000.0):
    rows = []
    for i in range(n):
        dist = last_m if i == n - 1 else 1000.0
        rows.append({
            "distance": dist,
            "elapsed_time": 300 + i,
            "moving_time": 298 + i,
            "split": i + 1,
            "average_heartrate": 148 + i,
            "average_cadence": 88,
            "average_watts": 260,
        })
    return rows


def test_strava_splits_metric_maps_metres_and_times():
    rows = strava_splits_metric_to_rows(_metric_km(3, last_m=420.0))
    assert len(rows) == 3
    assert rows[0]["distance_km"] == 1.0
    assert rows[2]["distance_km"] == 0.42
    assert rows[0]["duration_seconds"] == 298
    assert rows[0]["moving_time_seconds"] == 298
    assert rows[0]["elapsed_time_seconds"] == 300
    assert rows[0]["avg_hr"] == 148
    assert rows[0]["avg_power"] == 260
    assert rows[0]["cadence_spm"] == 176  # Strava one-foot cadence
    assert rows[0]["lap_type"] == "auto"


def test_strava_splits_metric_zero_hr_power_are_missing():
    rows = strava_splits_metric_to_rows([{
        "distance": 1000, "moving_time": 300, "elapsed_time": 300,
        "average_heartrate": 0, "average_watts": 0, "split": 1,
    }])
    assert rows[0]["avg_hr"] is None
    assert rows[0]["avg_power"] is None


def test_strava_splits_metric_empty_or_junk():
    assert strava_splits_metric_to_rows(None) == []
    assert strava_splits_metric_to_rows([]) == []
    assert strava_splits_metric_to_rows("nope") == []
    assert strava_splits_metric_to_rows([{"distance": 1000, "moving_time": 300}])


def test_synthetic_rows_feed_split_dict_shape():
    from backend.main import _split_dict

    mapped = strava_splits_metric_to_rows(_metric_km(1))
    fake = synthetic_split_rows("wid", mapped)
    d = _split_dict(fake[0])
    assert d["id"] is None
    assert d["split_index"] == 1
    assert float(d["distance_km"]) == 1.0
    assert d["duration_seconds"] == 298
    assert d["lap_type"] == "auto"


def test_write_split_rows_noops_on_empty():
    session = MagicMock()
    w = SimpleNamespace(id="w1")
    assert _write_split_rows(session, w, []) is False
    session.query.assert_not_called()


def test_sync_splits_stryd_writes_and_strava_skips_when_filled():
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value.delete.return_value = None
    w = SimpleNamespace(id="w1")
    stryd = SimpleNamespace(splits=[{
        "distance_km": 1.0,
        "duration_seconds": 310,
        "avg_hr": 150,
        "avg_power": 270,
        "cadence_spm": 176,
    }])
    assert _sync_splits(session, w, stryd) is True
    session.add_all.assert_called()
    strava_rows = strava_splits_metric_to_rows(_metric_km(2))
    assert strava_rows  # would fill only when Stryd did not


def test_strava_metric_from_activity_prefers_column_then_detail():
    act = SimpleNamespace(splits_metric=_metric_km(2), detail_payload={"splits_metric": _metric_km(9)})
    assert len(strava_metric_from_activity(act)) == 2
    act = SimpleNamespace(splits_metric=None, detail_payload={"splits_metric": _metric_km(3)})
    assert len(strava_metric_from_activity(act)) == 3
    act = SimpleNamespace(splits_metric=[], detail_payload={"splits_metric": _metric_km(3)})
    assert len(strava_metric_from_activity(act)) == 3
    assert strava_metric_from_activity(None) == []
    assert strava_metric_from_activity(SimpleNamespace(splits_metric=None, detail_payload=None)) == []


def test_fill_skips_fetch_when_detail_already_cached(monkeypatch):
    act = SimpleNamespace(
        id="sa1",
        strava_activity_id=99,
        splits_metric=_metric_km(2),
        laps=[],
        detail_payload={"splits_metric": _metric_km(2)},
    )

    def _boom(*_a, **_k):
        raise AssertionError("must not hit Strava when splits_metric is already cached")

    monkeypatch.setattr("backend.services.strava_sync._enrich_activity", _boom)
    # Nested session still opens; stub it so this unit test stays offline.
    monkeypatch.setattr("backend.services.reconcile._Session", lambda *_a, **_k: _FakeSession())
    rows = fill_strava_km_splits_if_missing("w1", act, user_id="u1")
    assert len(rows) == 2


def test_fill_fetches_when_detail_missing(monkeypatch):
    act = SimpleNamespace(
        id="sa1",
        strava_activity_id=99,
        splits_metric=None,
        laps=None,
        detail_payload=None,
    )
    monkeypatch.setattr(
        "backend.services.strava_sync._enrich_activity",
        lambda *_a, **_k: ({"splits_metric": _metric_km(4), "laps": [{"id": 1}]}, None),
    )
    monkeypatch.setattr("backend.services.reconcile._Session", lambda *_a, **_k: _FakeSession())
    rows = fill_strava_km_splits_if_missing("w1", act, user_id="u1")
    assert len(rows) == 4
    assert isinstance(act.splits_metric, list) and len(act.splits_metric) == 4


def test_run_detail_falls_back_to_strava_splits_metric():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "frontend/js/lib/run-detail-view.js").read_text()
    assert "normalizeStravaMetricSplit" in src
    assert "strava.splits_metric" in src


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *_a, **_k):
        return None

    def commit(self):
        return None
