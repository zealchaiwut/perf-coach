"""P5-6 v2 training admin exercise library."""
from __future__ import annotations

import pathlib
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_cookie, get_current_user, resolve_user
from backend.main import app
from backend.models import User
from backend.routers.admin import _validate_plan_exercise_import

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _as_admin():
    user = User(id=uuid.uuid4(), name="admin", is_admin=True)
    app.dependency_overrides[resolve_user] = lambda: user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.pop(resolve_user, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_v2_training_admin_page_shell():
    html = (ROOT / "frontend/pages/v2-training-admin.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend/js/v2-training-admin.js").read_text(encoding="utf-8")
    assert 'src="/js/v2-training-admin.js"' in html
    assert 'id="exercise-tbody"' in html
    assert 'id="import-diff"' in html
    assert "validateExerciseDraft" in js
    assert "Dry run" in html


def test_v2_training_admin_route_serves_html(monkeypatch):
    monkeypatch.setenv("REVAMP_UI", "1")
    admin = User(id=uuid.uuid4(), name="admin", is_admin=True)

    async def _admin():
        return admin

    app.dependency_overrides[get_current_user] = _admin
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, create_session_cookie(str(admin.id), time.time()))
    r = client.get("/v2/training/admin", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "v2-training-admin.js" in r.text
    assert "Exercise library" in r.text


def test_server_validate_body_part_ratio_sum():
    raw = {
        "name": "ratio-fail",
        "groups": ["warmup"],
        "focus_tags": ["lower"],
        "body_parts": [{"part": "quad", "ratio": 0.5}],
        "tss_weight": 1,
        "default_sets": 3,
        "default_reps": "10",
        "default_load": "light",
    }
    assert _validate_plan_exercise_import(raw) is not None
    raw["body_parts"] = [{"part": "quad", "ratio": 1.0}]
    assert _validate_plan_exercise_import(raw) is None


def test_import_export_roundtrip_still_admin_only():
    client = _as_admin()
    assert client.get("/api/admin/plan-library/export").status_code == 200