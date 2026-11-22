"""P5-3 Training Trends: fitness chart, weekly load, range picker."""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.services import revamp_trends as rt

TODAY = date(2026, 11, 12)
UID = uuid.uuid4()


def test_normalize_range_defaults_invalid():
    assert rt.normalize_range_key(None) == "3m"
    assert rt.normalize_range_key("bogus") == "3m"
    assert rt.normalize_range_key("6M") == "6m"


def test_range_dates_4w():
    f, t = rt.range_dates("4w", TODAY)
    assert t == TODAY
    assert (t - f).days == 27


def test_is_planned_down_week():
    assert rt.is_planned_down_week(80, 100) is True
    assert rt.is_planned_down_week(90, 100) is False
    assert rt.is_planned_down_week(None, 100) is False


def test_merge_phase_spans():
    rows = [
        {"week_start": "2026-10-06", "week_end": "2026-10-12", "phase": "taper"},
        {"week_start": "2026-10-13", "week_end": "2026-10-19", "phase": "taper"},
        {"week_start": "2026-10-20", "week_end": "2026-10-26", "phase": "race_week"},
    ]
    spans = rt._merge_phase_spans(rows)
    assert len(spans) == 2
    assert spans[0]["phase"] == "taper"
    assert spans[0]["end"] == "2026-10-19"
    assert spans[1]["label"] == "Race week"


@patch.object(rt, "get_snapshot_series")
@patch.object(rt, "week_target_and_phase", return_value=None)
@patch.object(rt, "weekly_rollups")
def test_trends_payload_series_from_pipeline(mock_rollups, _phase, mock_series):
    mock_series.return_value = [
        {
            "date": TODAY,
            "tss": 50,
            "ctl": 44.2,
            "atl": 38.1,
            "tsb": 6.1,
        }
    ]
    mock_rollups.return_value = [
        {
            "week_start": "2026-11-09",
            "tss_total": 120.0,
            "distance_km": 32.0,
            "hours": 4.5,
            "target_tss": 140.0,
            "phase": "build",
            "planned_tss": 20.0,
            "partial": True,
        }
    ]
    session = MagicMock()
    out = rt.trends_payload(session, UID, range_key="4w", today=TODAY)
    mock_series.assert_called_once()
    assert out["range"] == "4w"
    assert out["fitness"]["curves"][0]["ctl"] == 44.2
    assert out["fitness"]["current"]["tsb"] == 6.1
    week = out["weekly_load"]["weeks"][0]
    assert week["is_current_week"] is True
    assert week["outline_tss"] == 140.0


@patch.object(rt, "week_target_and_phase")
def test_build_phase_spans(mock_meta):
    def _meta(_uid, ws, **kwargs):
        if ws == date(2026, 11, 2):
            return {"phase": "taper", "target_tss": 200}
        if ws == date(2026, 11, 9):
            return {"phase": "race_week", "target_tss": 80}
        return None

    mock_meta.side_effect = _meta
    spans = rt.build_phase_spans(MagicMock(), UID, date(2026, 11, 1), date(2026, 11, 15), today=TODAY)
    assert len(spans) == 2
    assert {s["phase"] for s in spans} == {"taper", "race_week"}


def test_api_training_trends_revamp_requires_auth():
    from fastapi.testclient import TestClient

    from backend.main import app

    assert TestClient(app).get("/api/training/trends/revamp").status_code == 401


def test_api_training_trends_revamp_bad_range():
    from fastapi.testclient import TestClient

    from backend.auth import resolve_user
    from backend.main import app
    from backend.models import User

    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        r = TestClient(app).get("/api/training/trends/revamp?range=5y")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(resolve_user, None)