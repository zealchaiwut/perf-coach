"""Issue #1933 — superseded Plan GETs return 404; remaining callers stay."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User

UID = uuid.uuid4()
ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
HOME_JS = (ROOT / "frontend" / "js" / "v2-home.js").read_text(encoding="utf-8")
LEGACY_PLAN = (ROOT / "frontend" / "js" / "training-plan.js").read_text(encoding="utf-8")

REMOVED = (
    "/api/plan/revamp-week-board",
    "/api/plan/revamp-week-load",
    "/api/plan/revamp-warnings",
)


def test_removed_gets_are_404():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        client = TestClient(app)
        for path in REMOVED:
            res = client.get(path)
            assert res.status_code == 404, path
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_handlers_deleted_from_main():
    for path in REMOVED:
        assert f'@app.get("{path}")' not in MAIN
    assert '@app.get("/api/plan/revamp-week")' in MAIN
    assert '@app.post("/api/plan/revamp-warnings/apply")' in MAIN
    assert '@app.get("/api/plan/revamp-road-chart")' in MAIN
    assert '@app.get("/api/plan/week-bundle")' in MAIN


def test_kept_callers():
    assert "/api/plan/revamp-road-chart" in HOME_JS
    assert "/api/plan/week-bundle" in LEGACY_PLAN
    assert "def week_board" in (ROOT / "backend" / "services" / "revamp_week_board.py").read_text(encoding="utf-8")
    assert "def revamp_week_load" in (ROOT / "backend" / "services" / "revamp_load_plan.py").read_text(encoding="utf-8")
