"""Issue #1931 — ETag / Cache-Control on GET /api/plan/revamp-week."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services.log_etag import make_etag

UID = uuid.uuid4()
T1 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
WS = date(2026, 11, 16)
TODAY = date(2026, 11, 23)
ROOT = Path(__file__).resolve().parents[1]
PLAN_JS = (ROOT / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")


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


def test_revamp_week_200_then_304_then_write_200():
    sess = _sess()
    client = _client()
    stamps = {"cur": T1}
    builds = []

    def fake_etag(*_a, **_k):
        return make_etag(UID, "revamp-week", stamps["cur"])

    def fake_build(*_a, **_k):
        builds.append(1)
        return {"week_start": WS.isoformat(), "board": {"days": []}}

    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.services.log_etag.revamp_week_etag", side_effect=fake_etag),
            patch("backend.services.revamp_week.build_revamp_week", side_effect=fake_build),
        ):
            r1 = client.get(f"/api/plan/revamp-week?week_start={WS.isoformat()}")
            assert r1.status_code == 200, r1.text
            assert r1.headers.get("cache-control") == "private, no-cache"
            etag = r1.headers.get("etag")
            assert etag
            n_after_200 = len(builds)

            r2 = client.get(
                f"/api/plan/revamp-week?week_start={WS.isoformat()}",
                headers={"If-None-Match": etag},
            )
            assert r2.status_code == 304
            assert r2.content == b""
            assert r2.headers.get("etag") == etag
            assert r2.headers.get("cache-control") == "private, no-cache"
            assert len(builds) == n_after_200

            stamps["cur"] = T2
            r3 = client.get(
                f"/api/plan/revamp-week?week_start={WS.isoformat()}",
                headers={"If-None-Match": etag},
            )
            assert r3.status_code == 200
            assert r3.headers.get("etag") != etag
            assert len(builds) == n_after_200 + 1
    finally:
        _teardown()


def test_etag_changes_for_each_input_type():
    a = make_etag(UID, TODAY, "board", WS, T1, None, None, None, None)
    b = make_etag(UID, TODAY, "board", WS, T2, None, None, None, None)
    c = make_etag(UID, TODAY, "board,road", WS, T1, None, None, None, None)
    d = make_etag(UID, TODAY, "board", WS, T1, None, T2, None, None)
    e = make_etag(UID, TODAY, "board", WS, T1, None, None, T2, None)
    f = make_etag(UID, TODAY, "board", WS, T1, None, None, None, T2)
    tags = {a, b, c, d, e, f}
    assert len(tags) == 6


def test_frontend_sends_if_none_match():
    assert "If-None-Match" in PLAN_JS
    assert "r.status === 304" in PLAN_JS
    assert "_notModified" in PLAN_JS
