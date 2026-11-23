"""Issue #1937 — GET /api/performance/projection must not write race_predictions."""
from __future__ import annotations

import inspect
import logging
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.routers.performance_axes import get_performance_projection
from backend.services import projection_view as pv
from backend.services import race_calibration as rc
from backend.utils import query_log

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)
RACE_ID = uuid.uuid4()
EST = {"unavailable": False, "est_sec": 14893, "band_sec": 540}


def _sqlite_engine():
    return create_engine("sqlite://")


def _counting_session(sql_engine, inner):
    class Sess:
        def __init__(self, bind=None, **kwargs):
            self._sa = SASession(bind=sql_engine)
            self._sa.execute(text("SELECT 1"))

        def __enter__(self):
            return inner

        def __exit__(self, *exc):
            self.close()
            return False

        def close(self):
            self._sa.close()

        def __getattr__(self, name):
            return getattr(inner, name)

    return Sess


@pytest.fixture
def client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)
        query_log.disable()


def test_get_handler_and_builder_do_not_record():
    assert "record_prediction" not in inspect.getsource(get_performance_projection)
    assert "record_prediction(" not in inspect.getsource(pv.build_projection)
    assert "ensure_calibrations" not in inspect.getsource(pv.build_projection)


def test_projection_get_write_count_zero(client, caplog):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = MagicMock()
    q = inner.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = None
    q.all.return_value = []
    Sess = _counting_session(sql_engine, inner)
    empty = {
        "tiles": {},
        "built_from": {},
        "race": None,
        "goal": None,
        "chain": None,
        "chart": None,
        "invariants": {"ok": True, "violations": []},
    }

    with (
        caplog.at_level(logging.INFO, logger="backend.query_log"),
        patch("backend.routers.performance_axes.Session", Sess),
        patch("backend.services.projection_view.build_projection", return_value=empty),
        patch("backend.services.race_calibration.record_prediction") as rec,
    ):
        res = client.get("/api/performance/projection")

    assert res.status_code == 200, res.text
    rec.assert_not_called()
    records = [
        r
        for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == "/api/performance/projection"
    ]
    assert records, caplog.text
    assert records[-1].write_count == 0


def test_missing_today_history_still_returns_stored_days():
    a = SimpleNamespace(
        id=RACE_ID, name="A", race_date=date(2026, 12, 28), distance_km=42.2, role="a_race"
    )
    hist = [(date(2026, 11, 20), 14900), (date(2026, 11, 21), 14850)]
    prefs = SimpleNamespace(threshold_pace_seconds_per_km=330)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = prefs
    scores = {"overall": {"endurance": {"score": 41.0}, "speed": {"score": 45.0}}}
    with (
        patch.object(pv, "next_a_race", return_value=a),
        patch.object(pv, "estimate_race_finish", return_value=EST),
        patch("backend.services.race_calibration.load_calibrations", return_value=[]),
        patch("backend.services.race_calibration.record_prediction") as rec,
        patch.object(pv, "build_built_from", return_value={"available": False}),
        patch.object(pv, "_calibration_tiles", return_value=pv.build_tiles(None, [], None, None)),
        patch.object(pv, "goal_state", return_value={"time_sec": 16200, "state": "provisional", "editable": True}),
        patch.object(pv, "_block_start", return_value=date(2026, 11, 9)),
        patch.object(pv, "_markers", return_value=([], [], [])),
        patch.object(pv, "_history", return_value=hist),
        patch("backend.services.score_reader.get_scores", return_value=scores),
    ):
        out = pv.build_projection(db, UID, TODAY)
    rec.assert_not_called()
    dates = [h["date"] for h in out["chart"]["history"]]
    assert dates == ["2026-11-20", "2026-11-21"]
    assert "2026-11-23" not in dates


def test_record_todays_predictions_idempotent_across_two_runs():
    race = SimpleNamespace(id=RACE_ID, status="planned", race_date=date(2026, 12, 1))
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [race]
    with (
        patch("backend.services.race_finish_estimate.estimate_race_finish", return_value=EST),
        patch.object(rc, "record_prediction") as rec,
    ):
        n1 = rc.record_todays_predictions(session, UID, TODAY)
        n2 = rc.record_todays_predictions(session, UID, TODAY)
    assert n1 == n2 == 1
    assert rec.call_count == 2
    rec.assert_called_with(UID, RACE_ID, EST["est_sec"], EST["band_sec"], session)


def test_run_daily_predictions_two_users_ok():
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    fake.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(id=u1),
        SimpleNamespace(id=u2),
    ]
    with (
        patch("sqlalchemy.orm.Session", return_value=fake),
        patch.object(rc, "record_todays_predictions", return_value=1) as rec,
    ):
        out = rc.run_daily_predictions(TODAY)
    assert rec.call_count == 2
    assert out == {str(u1): "ok", str(u2): "ok"}


def test_worker_registers_race_predictions_job():
    src = Path("backend/worker_app.py").read_text()
    assert '"race_predictions": _h_race_predictions' in src
    assert "race_predictions:" in src
    assert "/internal/race-predictions/run" in src


def test_write_events_call_after_race_write():
    svc = Path("backend/services/projection_service.py").read_text()
    assert svc.count("after_race_write") >= 2
    main = Path("backend/main.py").read_text()
    assert main.count("after_race_write") >= 4
