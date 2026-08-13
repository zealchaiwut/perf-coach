"""Dashboard GETs read stored snapshots; the worker writes them.

Page load must not recompute endurance/speed or the plan bundle when a
summary_cache / computed_cache row already exists (even if the signature is
stale after a sync). Recalculate and precompute_user are the write path.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from backend.services import precompute, summary_cache_store
from backend.services.athlete_summaries import weekly_cache_key
from backend.utils.time import today_bangkok


def test_weekly_get_serves_stale_cache_without_recompute():
    from backend.main import get_athlete_weekly_summary

    user = MagicMock()
    user.id = uuid.uuid4()
    ws = today_bangkok() - timedelta(days=today_bangkok().weekday())
    stale = {
        "week_start": ws.isoformat(),
        "week_end": (ws + timedelta(days=6)).isoformat(),
        "distance_km": 42.0,
        "total_tss": 300,
        "session_count": 5,
        "duration_seconds": 18000,
        "note": "stale",
    }

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = MagicMock(id=user.id)
    mock_db.query.return_value.filter.return_value.one.return_value = (None, 1, None)

    with (
        patch("backend.main.Session", return_value=mock_db),
        patch("backend.main._summary_cache_get", return_value=None),
        patch("backend.main._summary_cache_get_latest", side_effect=lambda uid, key: stale if "weekly" in str(key) else None),
        patch("backend.services.athlete_summaries.compute_weekly_summary") as mock_compute,
    ):
        resp = get_athlete_weekly_summary(athlete_id=str(user.id), user=user, week=ws.isoformat())

    assert resp.body
    mock_compute.assert_not_called()
    import json
    body = json.loads(resp.body)
    assert body["note"] == "stale"
    assert body["week_start"] == ws.isoformat()


def test_plan_computed_get_returns_existing_cache_when_signature_stale():
    from backend.main import get_plan_computed

    user = MagicMock()
    user.id = uuid.uuid4()
    plan = MagicMock()
    plan.computed_cache = {"races": [{"id": "r1"}], "generated_at": "old"}
    plan.computed_signature = "old-sig"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with (
        patch("backend.main.Session", return_value=mock_db),
        patch("backend.main._resolve_or_create_plan", return_value=plan),
        patch("backend.main._plan_signature", return_value="new-sig"),
        patch("backend.main._compute_plan_bundle") as mock_compute,
    ):
        resp = get_plan_computed(user=user)

    mock_compute.assert_not_called()
    import json
    body = json.loads(resp.body)
    assert body["cached"] is False
    assert body["races"] == [{"id": "r1"}]


def test_precompute_user_warms_dashboard_caches():
    today = date.today()
    with (
        patch.object(precompute.training_load, "daily_update", return_value={
            "date": today, "tss": 0, "ctl": 1.0, "atl": 2.0, "tsb": -1.0, "acwr": None,
        }),
        patch.object(precompute, "_warm_performance", return_value="scored") as wp,
        patch.object(precompute, "_warm_summaries", return_value={"weeks": ["x"], "months": ["y"]}) as ws,
        patch.object(precompute, "_warm_plan_bundle", return_value="overlayed") as wb,
    ):
        out = precompute.precompute_user(str(uuid.uuid4()))

    wp.assert_called_once()
    ws.assert_called_once()
    wb.assert_called_once()
    assert out["performance"] == "scored"
    assert out["summaries"]["weeks"] == ["x"]
    assert out["plan_bundle"] == "overlayed"
    assert today.isoformat() in out["warmed"]


def test_weekly_period_keys_skip_l1():
    assert summary_cache_store.l1_cacheable("weekly") is True
    assert summary_cache_store.l1_cacheable(weekly_cache_key(date(2026, 8, 10))) is False
    assert summary_cache_store.l1_cacheable("performance") is True
