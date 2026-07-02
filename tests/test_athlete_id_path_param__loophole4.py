"""Tests for fix-loopholes Task 4: decorative athlete_id path params.

Six /api/athletes/{athlete_id}/... endpoints captured athlete_id in the URL
but never compared it to the session user — they silently returned the
session user's own data regardless of the id in the path. Now each returns
404 when the path id doesn't match the session user (matching the sibling
/api/athletes/{athlete_id}/races and /summary/monthly routes, which already
did this correctly).
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import User

_client = TestClient(app)

_ROUTES = [
    "/api/athletes/{}/daily-load?start_date=2026-01-01&end_date=2026-01-07",
    "/api/athletes/{}/duration-curve",
    "/api/athletes/{}/detected-prs",
    "/api/athletes/{}/performance",
    "/api/athletes/{}/summary/weekly",
    "/api/athletes/{}/run-personal-records",
]


def _as(user):
    async def _fake():
        return user
    app.dependency_overrides[resolve_user] = _fake


@pytest.fixture
def session_user():
    user = User(name="loophole4-" + uuid.uuid4().hex[:8])
    user.id = uuid.uuid4()
    _as(user)
    yield user
    app.dependency_overrides.pop(resolve_user, None)


@pytest.mark.parametrize("route_tmpl", _ROUTES)
def test_foreign_athlete_id_returns_404(session_user, route_tmpl):
    foreign_id = uuid.uuid4()
    assert foreign_id != session_user.id
    res = _client.get(route_tmpl.format(foreign_id))
    assert res.status_code == 404, (
        f"{route_tmpl}: expected 404 for foreign athlete_id, got {res.status_code}: {res.text}"
    )


@pytest.mark.parametrize("route_tmpl", _ROUTES)
def test_malformed_athlete_id_returns_404(session_user, route_tmpl):
    res = _client.get(route_tmpl.format("not-a-uuid"))
    assert res.status_code == 404, (
        f"{route_tmpl}: expected 404 for malformed athlete_id, got {res.status_code}: {res.text}"
    )
