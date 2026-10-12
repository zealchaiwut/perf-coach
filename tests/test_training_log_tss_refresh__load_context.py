"""Training log must stay 200 when TSS refresh commits with include_load_context."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from tests.test_surface_training_load_chart__528 import (
    _make_client,
    _make_session_mock,
    _make_snap,
    _teardown,
)


def test_training_log_ok_after_tss_persist_with_snapshot():
    """Regression: commit after persist must not detach today_snap (500 on /log)."""
    client = _make_client()
    snap = _make_snap(55.0, 60.0, -5.0)
    run = MagicMock()
    run.workout_type = "Run"
    run.tss_source = "stryd"
    run.id = "00000000-0000-0000-0000-000000000001"
    run.workout_date = date.today()
    run.name = "Test"
    run.tss = 22.0
    run.run_subtype = None
    run.duration_seconds = 3600
    run.distance_km = 10.0
    run.avg_hr = 140
    run.elevation_m = None
    run.source = "stryd"
    run.strava_activity_url = None
    run.stryd_activity_pk = 1
    run.strava_activity_pk = None
    run.remarks = None
    run.feeling = None

    sess = _make_session_mock(total_workout_days=20, today_snap=snap)
    sess.query.return_value.order_by.return_value.all.return_value = [run]

    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.main._persist_running_tss", return_value={"tss": 40, "method": "power"}),
        ):
            res = client.get("/api/training-log?include_load_context=true")
        assert res.status_code == 200, res.text
        assert res.json()["weeks"] is not None
        lc = res.json()["load_context"]
        assert lc["ctl"] == 55.0
    finally:
        _teardown()
