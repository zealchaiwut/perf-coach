"""P5-7 pending exercise queue API shape."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services.pending_exercises import preview_remap


@pytest.fixture
def admin_client():
    user = User(id=uuid.uuid4(), name="admin", is_admin=True)
    app.dependency_overrides[resolve_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.pop(resolve_user, None)


def test_list_pending_includes_remap_preview(admin_client):
    r = admin_client.get("/api/admin/pending-exercises")
    assert r.status_code == 200
    assert "pending" in r.json()


def test_preview_remap_returns_counts():
    from backend.db import engine
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        out = preview_remap(session, display_name="nonexistent-custom-zzz-1869")
    assert out["sessions"] == 0
    assert out["weeks"] == 0


def test_admin_page_has_pending_queue_markup():
    from pathlib import Path

    html = Path("frontend/pages/v2-training-admin.html").read_text(encoding="utf-8")
    assert 'id="pending-queue-card"' in html
    assert "data-pending-map" in Path("frontend/js/v2-training-admin.js").read_text(encoding="utf-8")