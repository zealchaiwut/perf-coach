"""Issue #1921 — ETag / Cache-Control on weekly-rollup and training/month."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services.log_etag import make_etag

UID = uuid.uuid4()
T1 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


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


def test_weekly_rollup_200_then_304_then_write_200():
    sess = _sess()
    client = _client()
    stamps = {"cur": T1}
    rollup_calls = []

    def fake_range(*_a, **_k):
        return make_etag(UID, "week", stamps["cur"])

    def fake_week(*_a, **_k):
        rollup_calls.append(1)
        return {"week_start": "2026-11-17", "tss_total": 1, "session_count": 1}

    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.services.log_etag.range_etag", side_effect=fake_range),
            patch("backend.services.weekly_rollup.weekly_rollup", side_effect=fake_week),
            patch("backend.services.weekly_rollup.weekly_rollups", return_value=[]),
        ):
            r1 = client.get("/api/weekly-rollup?week_start=2026-11-17")
            assert r1.status_code == 200, r1.text
            assert r1.headers.get("cache-control") == "private, no-cache"
            etag = r1.headers.get("etag")
            assert etag
            n_after_200 = len(rollup_calls)

            r2 = client.get(
                "/api/weekly-rollup?week_start=2026-11-17",
                headers={"If-None-Match": etag},
            )
            assert r2.status_code == 304
            assert r2.content == b""
            assert r2.headers.get("etag") == etag
            assert r2.headers.get("cache-control") == "private, no-cache"
            assert len(rollup_calls) == n_after_200

            stamps["cur"] = T2
            r3 = client.get(
                "/api/weekly-rollup?week_start=2026-11-17",
                headers={"If-None-Match": etag},
            )
            assert r3.status_code == 200
            assert r3.headers.get("etag") != etag
            assert len(rollup_calls) == n_after_200 + 1
    finally:
        _teardown()


def test_training_month_200_then_304_then_write_200():
    sess = _sess()
    client = _client()
    stamps = {"cur": T1}
    builds = []

    def fake_range(*_a, **_k):
        return make_etag(UID, "month", stamps["cur"])

    def fake_month(*_a, **_k):
        builds.append(1)
        return {"month": "2026-11", "weeks": []}

    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.services.log_etag.range_etag", side_effect=fake_range),
            patch("backend.main._training_month", side_effect=fake_month),
        ):
            r1 = client.get("/api/training/month?month=2026-11")
            assert r1.status_code == 200, r1.text
            assert r1.headers.get("cache-control") == "private, no-cache"
            etag = r1.headers.get("etag")
            n = len(builds)

            r2 = client.get(
                "/api/training/month?month=2026-11",
                headers={"If-None-Match": etag},
            )
            assert r2.status_code == 304
            assert r2.content == b""
            assert len(builds) == n

            stamps["cur"] = T2
            r3 = client.get(
                "/api/training/month?month=2026-11",
                headers={"If-None-Match": etag},
            )
            assert r3.status_code == 200
            assert r3.headers.get("etag") != etag
            assert len(builds) == n + 1
    finally:
        _teardown()


def test_write_in_range_changes_etag():
    a = make_etag(UID, "p", T1)
    b = make_etag(UID, "p", T2)
    assert a != b
