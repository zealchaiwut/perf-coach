"""Issue #1912 — per-request query_count / duration_ms on Log endpoints."""
from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.utils import query_log

UID = uuid.uuid4()

_ROLLUP = {
    "week_start": "2026-11-17",
    "week_end": "2026-11-23",
    "tss_total": 0,
    "session_count": 0,
    "distance_km": 0,
    "hours": 0,
    "planned_tss": 0,
    "target_tss": None,
}


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


def _mock_orm():
    inner = MagicMock()
    q = inner.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.distinct.return_value = q
    q.group_by.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    q.count.return_value = 0
    inner.__enter__.return_value = inner
    inner.__exit__.return_value = False
    return inner


@pytest.fixture
def client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)
        query_log.disable()


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/api/training-log?from=2026-11-01&to=2026-11-07", "/api/training-log"),
        ("/api/weekly-rollup", "/api/weekly-rollup"),
        ("/api/training/month?month=2026-11", "/api/training/month"),
    ],
)
def test_log_endpoints_emit_query_count(client, caplog, path, expected):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)

    def _fire_rollup(*_a, **_k):
        with SASession(sql_engine) as s:
            s.execute(text("SELECT 1"))
        return dict(_ROLLUP)

    def _fire_rollups(*_a, **_k):
        with SASession(sql_engine) as s:
            s.execute(text("SELECT 1"))
        return [dict(_ROLLUP)]

    def _fire_month(*_a, **_k):
        with SASession(sql_engine) as s:
            s.execute(text("SELECT 1"))
        return {"month": "2026-11", "weeks": []}

    with (
        caplog.at_level(logging.INFO, logger="backend.query_log"),
        patch("backend.main.Session", Sess),
        patch("backend.services.weekly_rollup.weekly_rollup", side_effect=_fire_rollup),
        patch("backend.services.weekly_rollup.weekly_rollups", side_effect=_fire_rollups),
        patch("backend.main._training_month", side_effect=_fire_month),
        patch("backend.services.training_month.training_month", side_effect=_fire_month),
    ):
        res = client.get(path)

    assert res.status_code == 200, res.text
    records = [
        r
        for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == expected
    ]
    assert records, caplog.text
    rec = records[-1]
    assert isinstance(rec.query_count, int)
    assert rec.query_count > 0
    assert isinstance(rec.duration_ms, (int, float))
    assert rec.user_id == str(UID)


def test_query_log_off_registers_no_listener(monkeypatch):
    monkeypatch.delenv("PERF_QUERY_LOG", raising=False)
    query_log.disable()
    engine = _sqlite_engine()
    before = set(query_log._installed_ids)
    # Span no-ops when disabled and must not install a listener.
    with query_log.request_span("/api/training-log", UID):
        with SASession(engine) as s:
            s.execute(text("SELECT 1"))
    assert query_log._installed_ids == before
