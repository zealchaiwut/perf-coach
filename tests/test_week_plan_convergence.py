"""Tests for issue #1516: week_plan convergence across API / service.

The canonical API shape is {"days": [...]}.
The service (_assemble_week_plan) returns a list; the endpoint normalizes it to dict.
"""
from __future__ import annotations

import ast
import importlib
import inspect

import pytest


# ── AC1: endpoint returns week_plan as a dict ─────────────────────────────────

def test_ac1_endpoint_week_plan_is_dict():
    """AC1: GET /api/brief/today returns week_plan as a dict, not a list."""
    import time
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from backend.auth import create_session_cookie, COOKIE_NAME
    from backend.main import app, resolve_user

    _USER_ID = "00000000-0000-0000-0000-000000001516"
    _FAKE = {
        "schema_version": 2,
        "for_date": "2026-07-17",
        "generated_at": "2026-07-17T08:00:00+07:00",
        "today": {"date": "2026-07-17", "session_type": None, "planned": False,
                  "intensity": None, "duration_min": None, "notes": None},
        "tomorrow": {"date": "2026-07-18", "session_type": None, "planned": False,
                     "intensity": None, "duration_min": None, "notes": None},
        "form": {"ctl": 40.0, "atl": 38.0, "tsb": 2.0, "ramp": 1.0,
                 "flags": {"guardrail_state": "ok"}, "interpretation": "Neutral"},
        "recent_wrap": {"window_days": 14, "sessions_planned": 5,
                        "sessions_completed": 4, "adherence": 0.8,
                        "load_trend": 1.0, "highlights_md": ""},
        "weight": {"current_kg": 72.0, "trend_7d": 0.0, "trend_28d": 0.0,
                   "target_kg": 70.0, "target_date": None,
                   "pace_kg_per_week": 0.0, "on_track": False,
                   "projection_date": None},
        "advisories": [],
        "actions": [],
        "week_plan": [
            {"date": "2026-07-18", "day": "Sat", "session_type": "run",
             "intensity": "easy", "duration_min": 60, "planned": True},
        ],
    }

    mock_user = MagicMock()
    mock_user.id = _USER_ID

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    token = create_session_cookie(_USER_ID, time.time())
    try:
        with TestClient(app, cookies={COOKIE_NAME: token},
                        raise_server_exceptions=False) as client:
            with patch("backend.main.build_brief", return_value=dict(_FAKE)):
                r = client.get("/api/brief/today")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body.get("week_plan"), dict), (
            f"Expected week_plan to be a dict, got {type(body.get('week_plan'))}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC2: endpoint does not duplicate service's week_plan query ────────────────

def test_ac2_build_week_plan_not_in_main():
    """AC2: _build_week_plan (duplicate helper) is not defined in backend/main.py."""
    import backend.main as m
    assert not hasattr(m, "_build_week_plan"), (
        "_build_week_plan still exists in backend/main — remove the duplicate helper"
    )


# ── AC3: service list is wrapped in {"days": list} by the endpoint ───────────

def test_ac3_service_list_wrapped_in_days_key():
    """AC3: when service returns week_plan as a list, endpoint wraps it in {'days': list}."""
    import time
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from backend.auth import create_session_cookie, COOKIE_NAME
    from backend.main import app, resolve_user

    _USER_ID = "00000000-0000-0000-0000-000000001516"
    _DAY = {"date": "2026-07-18", "day": "Sat", "session_type": "run",
            "intensity": "easy", "duration_min": 45, "planned": True}
    _FAKE = {
        "schema_version": 2,
        "for_date": "2026-07-17",
        "generated_at": "2026-07-17T08:00:00+07:00",
        "today": {"date": "2026-07-17", "session_type": None, "planned": False,
                  "intensity": None, "duration_min": None, "notes": None},
        "tomorrow": {"date": "2026-07-18", "session_type": None, "planned": False,
                     "intensity": None, "duration_min": None, "notes": None},
        "form": {"ctl": 40.0, "atl": 38.0, "tsb": 2.0, "ramp": 1.0,
                 "flags": {"guardrail_state": "ok"}, "interpretation": "Neutral"},
        "recent_wrap": {"window_days": 14, "sessions_planned": 5,
                        "sessions_completed": 4, "adherence": 0.8,
                        "load_trend": 1.0, "highlights_md": ""},
        "weight": {"current_kg": 72.0, "trend_7d": 0.0, "trend_28d": 0.0,
                   "target_kg": 70.0, "target_date": None,
                   "pace_kg_per_week": 0.0, "on_track": False,
                   "projection_date": None},
        "advisories": [],
        "actions": [],
        "week_plan": [_DAY],
    }

    mock_user = MagicMock()
    mock_user.id = _USER_ID

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    token = create_session_cookie(_USER_ID, time.time())
    try:
        with TestClient(app, cookies={COOKIE_NAME: token},
                        raise_server_exceptions=False) as client:
            with patch("backend.main.build_brief", return_value=dict(_FAKE)):
                r = client.get("/api/brief/today")
        body = r.json()
        wp = body.get("week_plan")
        assert isinstance(wp, dict), f"week_plan is {type(wp)}, expected dict"
        assert "days" in wp, f"week_plan has no 'days' key: {wp}"
        assert wp["days"] == [_DAY], f"week_plan.days mismatch: {wp['days']}"
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC4: empty week_plan returns {"days": []} ─────────────────────────────────

def test_ac4_empty_week_plan_is_days_empty_list():
    """AC4: when service returns an empty list, endpoint returns {'days': []}."""
    import time
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from backend.auth import create_session_cookie, COOKIE_NAME
    from backend.main import app, resolve_user

    _USER_ID = "00000000-0000-0000-0000-000000001516"
    _FAKE = {
        "schema_version": 2,
        "for_date": "2026-07-17",
        "generated_at": "2026-07-17T08:00:00+07:00",
        "today": {"date": "2026-07-17", "session_type": None, "planned": False,
                  "intensity": None, "duration_min": None, "notes": None},
        "tomorrow": {"date": "2026-07-18", "session_type": None, "planned": False,
                     "intensity": None, "duration_min": None, "notes": None},
        "form": {"ctl": 40.0, "atl": 38.0, "tsb": 2.0, "ramp": 1.0,
                 "flags": {"guardrail_state": "ok"}, "interpretation": "Neutral"},
        "recent_wrap": {"window_days": 14, "sessions_planned": 5,
                        "sessions_completed": 4, "adherence": 0.8,
                        "load_trend": 1.0, "highlights_md": ""},
        "weight": {"current_kg": 72.0, "trend_7d": 0.0, "trend_28d": 0.0,
                   "target_kg": 70.0, "target_date": None,
                   "pace_kg_per_week": 0.0, "on_track": False,
                   "projection_date": None},
        "advisories": [],
        "actions": [],
        "week_plan": [],
    }

    mock_user = MagicMock()
    mock_user.id = _USER_ID

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    token = create_session_cookie(_USER_ID, time.time())
    try:
        with TestClient(app, cookies={COOKIE_NAME: token},
                        raise_server_exceptions=False) as client:
            with patch("backend.main.build_brief", return_value=dict(_FAKE)):
                r = client.get("/api/brief/today")
        body = r.json()
        wp = body.get("week_plan")
        assert wp == {"days": []}, (
            f"Expected week_plan == {{'days': []}}, got {wp}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC5: docs document the {"days": [...]} dict shape ────────────────────────

def test_ac5_docs_document_days_key():
    """AC5: docs/features/api.md documents week_plan with a 'days' key."""
    api_doc = open("docs/features/api.md").read()
    assert '"days"' in api_doc or "'days'" in api_doc, (
        "docs/features/api.md does not document the 'days' key for week_plan"
    )
    assert "planned_sessions" not in api_doc or api_doc.index('"days"') < api_doc.index("planned_sessions"), (
        "docs/features/api.md still documents the old planned_sessions shape for week_plan"
    )
