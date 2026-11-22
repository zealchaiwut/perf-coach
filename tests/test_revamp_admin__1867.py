"""P5-5 Admin role and admins-only v2 tab."""
from __future__ import annotations

import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth import get_current_user, resolve_user
from backend.main import app
from backend.models import User

UID_ADMIN = uuid.uuid4()
UID_ATHLETE = uuid.uuid4()


def _as(user: User):
    app.dependency_overrides[resolve_user] = lambda: user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(resolve_user, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_plan_exercises_admin_ok():
    client = _as(User(id=UID_ADMIN, name="admin", is_admin=True))
    r = client.get("/api/admin/plan-exercises", headers={"Accept": "application/json"})
    assert r.status_code == 200


def test_plan_exercises_forbidden_for_non_admin():
    client = _as(User(id=UID_ATHLETE, name="alice", is_admin=False))
    r = client.get("/api/admin/plan-exercises", headers={"Accept": "application/json"})
    assert r.status_code == 403
    assert "Admin role" in r.json()["detail"]


def test_pending_exercises_requires_role():
    client = _as(User(id=UID_ATHLETE, name="alice", is_admin=False))
    assert client.get("/api/admin/pending-exercises").status_code == 403


@pytest.mark.parametrize("page", ["v2-home.html", "v2-training-plan.html", "v2-training-trends.html"])
def test_v2_pages_hide_admin_tab_by_default(page):
    html = pathlib.Path("frontend/pages") / page
    text = html.read_text(encoding="utf-8")
    assert 'id="rv-admin-tab" hidden' in text
    assert "ADMINS ONLY" in text


def test_v2_training_admin_blocked_for_non_admin(monkeypatch):
    import time

    from backend.auth import COOKIE_NAME, create_session_cookie

    monkeypatch.setenv("REVAMP_UI", "1")
    athlete = User(id=UID_ATHLETE, name="alice", is_admin=False)

    async def _athlete_user():
        return athlete

    app.dependency_overrides[get_current_user] = _athlete_user
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, create_session_cookie(str(UID_ATHLETE), time.time()))
    r = client.get("/v2/training/admin", headers={"Accept": "text/html"})
    assert r.status_code == 403
    assert "403" in r.text or "Admin only" in r.text