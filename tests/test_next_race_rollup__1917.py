"""Issue #1917 — next_race on weekly-rollup; Log drops /api/races."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services.weekly_rollup import next_race_brief

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)


def _client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _sess():
    s = MagicMock()
    s.__enter__.return_value = s
    s.__exit__.return_value = False
    return s


def test_next_race_brief_present():
    race = SimpleNamespace(name="Bangkok Marathon", race_date=date(2026, 12, 6), priority="A")
    sess = MagicMock()
    q = sess.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = race
    assert next_race_brief(sess, UID, TODAY) == {
        "name": "Bangkok Marathon",
        "race_date": "2026-12-06",
        "priority": "A",
    }


def test_next_race_brief_absent():
    sess = MagicMock()
    q = sess.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = None
    assert next_race_brief(sess, UID, TODAY) is None


def test_weekly_rollup_range_includes_next_race():
    sess = _sess()
    q = sess.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = SimpleNamespace(
        name="Bangkok Marathon", race_date=date(2026, 12, 6), priority="A"
    )
    client = _client()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.services.log_etag.range_etag", return_value='"abc"'),
            patch("backend.services.log_etag.not_modified", return_value=False),
            patch(
                "backend.services.weekly_rollup.weekly_rollups",
                return_value=[{"week_start": "2026-11-17", "tss_total": 0}],
            ),
            patch("backend.services.revamp_plan_settings.plan_context", return_value=None),
        ):
            r = client.get("/api/weekly-rollup?from=2026-11-17&to=2026-11-23")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "weeks" in body
        assert body["next_race"] == {
            "name": "Bangkok Marathon",
            "race_date": "2026-12-06",
            "priority": "A",
        }
    finally:
        _teardown()


def test_weekly_rollup_range_next_race_null():
    sess = _sess()
    q = sess.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = None
    client = _client()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.services.log_etag.range_etag", return_value='"abc"'),
            patch("backend.services.log_etag.not_modified", return_value=False),
            patch("backend.services.weekly_rollup.weekly_rollups", return_value=[]),
            patch("backend.services.revamp_plan_settings.plan_context", return_value=None),
        ):
            r = client.get("/api/weekly-rollup?from=2026-11-17&to=2026-11-23")
        assert r.status_code == 200, r.text
        assert r.json()["next_race"] is None
        assert r.json()["weeks"] == []
    finally:
        _teardown()


def test_log_js_reads_next_race_and_skips_races_api():
    assert "data.next_race" in LOG_JS
    assert "/api/races" not in LOG_JS
    assert "loadRaceLine" not in LOG_JS
    assert "function loadChart" in LOG_JS
