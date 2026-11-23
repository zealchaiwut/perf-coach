"""Issue #1929 — Plan writes return fresh board/load/road_column/warnings."""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services import revamp_week as rw

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)
WS = date(2026, 11, 16)
ROOT = Path(__file__).resolve().parents[1]
PLAN_JS = (ROOT / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")
BOARD_JS = (ROOT / "frontend" / "js" / "v2-plan-week-board.js").read_text(encoding="utf-8")

SECTIONS = {
    "board": {"week_start": WS.isoformat(), "days": []},
    "week_load": {"target_tss": 100, "logged_tss": 10, "planned_tss": 20},
    "road_column": {
        "week_start": WS.isoformat(),
        "state": "current",
        "target_tss": 100,
        "planned_tss": 20,
    },
    "warnings": {"layout_error": None, "clashes": []},
}


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


def test_road_column_matches_chart_item():
    col = {
        "week_start": WS.isoformat(),
        "state": "current",
        "target_tss": 90,
        "planned_tss": 40,
    }
    road = {"mode": "block", "columns": [{"week_start": "2026-11-10"}, col]}
    assert rw.road_column_for_week(road, WS) == col


def test_mutation_sections_shape():
    session = MagicMock()
    full = {
        "week_start": WS.isoformat(),
        "board": SECTIONS["board"],
        "week_load": SECTIONS["week_load"],
        "road": {"columns": [SECTIONS["road_column"]]},
        "warnings": SECTIONS["warnings"],
    }
    with patch.object(rw, "build_revamp_week", return_value=full) as build:
        out = rw.mutation_sections(session, UID, week_start=WS, today=TODAY)
    build.assert_called_once()
    assert out["board"] == SECTIONS["board"]
    assert out["week_load"] == SECTIONS["week_load"]
    assert out["road_column"] == SECTIONS["road_column"]
    assert out["warnings"] == SECTIONS["warnings"]


def test_suggest_apply_without_return_unchanged():
    client = _client()
    sess = _sess()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch(
                "backend.services.revamp_suggest_sessions.apply_week_suggestions",
                return_value={"created": 2},
            ),
            patch("backend.services.revamp_week.mutation_sections") as mut,
        ):
            res = client.post("/api/plan/revamp-suggest/apply", json={"proposed": []})
        assert res.status_code == 200
        assert res.json() == {"created": 2}
        mut.assert_not_called()
    finally:
        _teardown()


def test_suggest_apply_return_sections():
    client = _client()
    sess = _sess()
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch(
                "backend.services.revamp_suggest_sessions.apply_week_suggestions",
                return_value={"created": 1},
            ),
            patch("backend.services.revamp_week.mutation_sections", return_value=SECTIONS),
        ):
            res = client.post(
                "/api/plan/revamp-suggest/apply?return=sections",
                json={"proposed": [{"planned_date": WS.isoformat(), "session_type": "run"}]},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["created"] == 1
        assert body["board"] == SECTIONS["board"]
        assert body["week_load"] == SECTIONS["week_load"]
        assert body["road_column"]["week_start"] == WS.isoformat()
        assert "warnings" in body
    finally:
        _teardown()


def test_frontend_patches_road_and_limits_drag_requests():
    assert "function patchRoadColumn" in PLAN_JS
    assert "function applyMutation" in PLAN_JS
    assert "return=sections" in BOARD_JS
    assert "planned-sessions/' + id + '?return=sections'" in BOARD_JS
    assert "applyReturned" in BOARD_JS
    # Drag is rule-evaluate + PATCH with return=sections; no extra GET on success.
    apply = BOARD_JS.split("function applyMove")[1].split("function bindDnD")[0]
    assert "ruleEvaluate" in apply
    assert "patchMove" in apply
    assert "applyReturned(res.body)" in apply
    assert "refresh();\n          });\n        }\n        doPatch" not in apply
