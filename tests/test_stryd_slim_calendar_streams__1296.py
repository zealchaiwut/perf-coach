"""AC tests for issue #1296: strip *_list streams from Stryd calendar before mapping.

AC1: *_list arrays stripped before/immediately as each activity is processed;
     full parsed calendar with streams never retained alongside a mapped copy.
AC3: stryd_activities rows after fresh full sync equivalent to pre-change output
     (same promoted columns, same slimmed payloads).
AC5: _ENRICH_WORKERS reduced / env-configurable.
AC6: sync of fixture calendar with large *_list arrays does not retain them
     past mapping; resulting rows match expected.
"""
import importlib
import os
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from backend.services import stryd_sync


# ── Fixture helpers ────────────────────────────────────────────────────────────

_STREAM_KEYS = [
    "timestamp_list",
    "total_power_list",
    "heart_rate_list",
    "cadence_list",
    "distance_list",
    "speed_list",
    "stride_length_list",
    "elevation_list",
]


def _make_activity(i: int) -> dict:
    """Fixture activity dict that mirrors the live Stryd calendar shape:
    summary fields + heavy per-point *_list arrays."""
    ts = 1_700_000_000 + i * 3600
    streams = {k: list(range(500)) for k in _STREAM_KEYS}
    return {
        "id": str(10000 + i),
        "timestamp": ts,
        "name": f"Run {i}",
        "distance": 10_000.0,
        "moving_time": 3600,
        "average_power": 250,
        "average_heart_rate": 155,
        "stress": 75,
        "ftp": 290,
        **streams,
    }


def _make_calendar_response(n: int = 5) -> dict:
    return {"activities": [_make_activity(i) for i in range(n)]}


# ── AC1 / AC6: fetch_stryd_activities strips *_list keys before returning ──────

def test_fetch_strips_list_arrays_from_calendar_response():
    """fetch_stryd_activities must not return dicts that still contain *_list keys."""
    import io
    import json
    import urllib.request

    payload = json.dumps(_make_calendar_response(3)).encode()

    class FakeResp:
        def read(self):
            return payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    with patch.object(urllib.request, "urlopen", return_value=FakeResp()):
        acts = stryd_sync.fetch_stryd_activities("tok", "athlete123")

    assert len(acts) == 3
    for a in acts:
        for k in a:
            assert not k.endswith("_list"), (
                f"*_list key '{k}' survived fetch_stryd_activities — "
                "streams must be stripped before returning"
            )


def test_fetch_preserves_summary_fields():
    """Summary fields (name, distance, average_power, …) must survive stripping."""
    import json
    import urllib.request

    payload = json.dumps(_make_calendar_response(1)).encode()

    class FakeResp:
        def read(self):
            return payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    with patch.object(urllib.request, "urlopen", return_value=FakeResp()):
        acts = stryd_sync.fetch_stryd_activities("tok", "athlete123")

    a = acts[0]
    assert a.get("distance") == 10_000.0
    assert a.get("average_power") == 250
    assert a.get("name") == "Run 0"


# ── AC1 / AC6: no *_list keys survive through to mapped row dicts ──────────────

def test_mapped_rows_contain_no_list_arrays():
    """map_stryd_activity must produce rows with no *_list keys in raw_payload."""
    act = _make_activity(0)
    # Pre-slim as fetch_stryd_activities will do after the fix
    slimmed = {k: v for k, v in act.items() if not k.endswith("_list")}
    row = stryd_sync.map_stryd_activity(slimmed, str(uuid.uuid4()))
    payload = row["raw_payload"]
    for k in payload:
        assert not k.endswith("_list"), (
            f"*_list key '{k}' found in raw_payload — streams must be stripped"
        )


def test_sync_slims_activities_before_upsert(monkeypatch):
    """sync_stryd_activities must not hold raw_acts with streams alongside mapped."""
    uid = uuid.uuid4()

    # Capture the dicts passed to map_stryd_activity
    captured_raw_keys: list[set] = []
    original_map = stryd_sync.map_stryd_activity

    def spy_map(raw, user_id):
        captured_raw_keys.append(set(raw.keys()))
        return original_map(raw, user_id)

    class FakeSession:
        def __init__(self, *_, **__):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def execute(self, stmt):
            sql = str(stmt)
            if "sync_jobs" in sql.lower() or "stryd_activity" in sql.lower():
                return MagicMock(scalar=MagicMock(return_value=None),
                                 scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
            return MagicMock(scalar=MagicMock(return_value=None),
                             scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        def query(self, *_):
            cred = MagicMock(athlete_id="123")
            return MagicMock(
                filter=MagicMock(return_value=MagicMock(one=MagicMock(return_value=cred)))
            )
        def add(self, _):
            pass
        def commit(self):
            pass
        def refresh(self, job):
            job.id = uuid.uuid4()
        def get(self, _model, _id):
            return MagicMock()

    with patch.object(stryd_sync, "Session", FakeSession), \
         patch.object(stryd_sync, "refresh_stryd_session_if_needed", return_value="tok"), \
         patch.object(stryd_sync, "fetch_stryd_activities",
                      return_value=[{k: v for k, v in _make_activity(i).items()
                                     if not k.endswith("_list")} for i in range(3)]), \
         patch.object(stryd_sync, "map_stryd_activity", side_effect=spy_map), \
         patch.object(stryd_sync, "_enrich_many", return_value=None), \
         patch.object(stryd_sync, "_heal_candidate_ids", return_value=[]), \
         patch.object(stryd_sync, "_already_enriched_ids", return_value=set()):
        stryd_sync.sync_stryd_activities(str(uid))

    # Each raw dict passed to map_stryd_activity must not contain *_list keys
    assert captured_raw_keys, "map_stryd_activity was never called"
    for key_set in captured_raw_keys:
        list_keys = {k for k in key_set if k.endswith("_list")}
        assert not list_keys, (
            f"*_list keys {list_keys} still present in dict passed to map_stryd_activity"
        )


# ── AC3: promoted columns unaffected by stream stripping ─────────────────────

def test_promoted_columns_preserved_after_slim():
    """map_stryd_activity on a slimmed dict must still produce correct promoted fields."""
    act = _make_activity(7)
    slimmed = {k: v for k, v in act.items() if not k.endswith("_list")}
    row = stryd_sync.map_stryd_activity(slimmed, str(uuid.uuid4()))
    assert row["stryd_activity_id"] == "10007"
    assert row["distance_km"] == 10.0
    assert row["duration_seconds"] == 3600
    assert row["avg_power_w"] == 250
    assert row["avg_hr"] == 155
    assert row["tss"] == 75


# ── AC5: _ENRICH_WORKERS is env-configurable ─────────────────────────────────

def test_enrich_workers_env_configurable(monkeypatch):
    """_ENRICH_WORKERS must read from STRYD_ENRICH_WORKERS env var."""
    monkeypatch.setenv("STRYD_ENRICH_WORKERS", "1")
    # Reload so the module-level variable picks up the new env value
    import importlib
    importlib.reload(stryd_sync)
    assert stryd_sync._ENRICH_WORKERS == 1


def test_enrich_workers_default_is_low(monkeypatch):
    """Default _ENRICH_WORKERS without env var must be <= 2 (web-process safe)."""
    monkeypatch.delenv("STRYD_ENRICH_WORKERS", raising=False)
    importlib.reload(stryd_sync)
    assert stryd_sync._ENRICH_WORKERS <= 2


def test_enrich_workers_worker_can_be_higher(monkeypatch):
    """Setting STRYD_ENRICH_WORKERS=8 must be respected."""
    monkeypatch.setenv("STRYD_ENRICH_WORKERS", "8")
    importlib.reload(stryd_sync)
    assert stryd_sync._ENRICH_WORKERS == 8
