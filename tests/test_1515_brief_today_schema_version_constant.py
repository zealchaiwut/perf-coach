"""Tests for issue #1515: /api/brief/today must reference SCHEMA_VERSION constant.

The endpoint must not hardcode schema_version = 3; it must derive the value
from daily_brief.SCHEMA_VERSION so bumping the constant is automatically
reflected in the API response.
"""
from __future__ import annotations

import ast
import inspect
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import backend.services.daily_brief as _daily_brief_module
from backend.auth import COOKIE_NAME, create_session_cookie
from backend.main import app, resolve_user

_USER_ID = "00000000-0000-0000-0000-000000001515"

_FAKE_BRIEF = {
    "schema_version": _daily_brief_module.SCHEMA_VERSION,
    "for_date": "2026-08-06",
    "generated_at": "2026-08-06T08:00:00+07:00",
    "today": {
        "date": "2026-08-06",
        "session_type": "run",
        "planned": True,
        "intensity": "easy",
        "duration_min": 50,
        "notes": None,
    },
    "tomorrow": {
        "date": "2026-08-07",
        "session_type": None,
        "planned": False,
        "intensity": None,
        "duration_min": None,
        "notes": None,
    },
    "form": {
        "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
        "ramp": 1.2, "flags": {"guardrail_state": "ok"},
        "interpretation": "Neutral",
    },
    "recent_wrap": {
        "window_days": 14,
        "sessions_planned": 10,
        "sessions_completed": 8,
        "adherence": 0.8,
        "load_trend": 1.2,
        "highlights_md": "Good week.",
    },
    "weight": {
        "current_kg": 72.5,
        "trend_7d": -0.2,
        "trend_28d": -0.5,
        "target_kg": 70.0,
        "target_date": "2026-09-01",
        "pace_kg_per_week": -0.2,
        "on_track": True,
        "projection_date": "2026-08-25",
    },
    "advisories": [],
    "actions": [],
    "week_plan": {"days": []},
}


def _make_auth_client():
    mock_user = MagicMock()
    mock_user.id = _USER_ID

    async def _fake_resolve_user():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve_user
    token = create_session_cookie(_USER_ID, time.time())
    client = TestClient(app, cookies={COOKIE_NAME: token}, raise_server_exceptions=False)
    return client, mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


# ── AC1: schema_version in response equals daily_brief.SCHEMA_VERSION ────────

def test_ac1_schema_version_matches_constant():
    """AC1: schema_version in response equals daily_brief.SCHEMA_VERSION constant."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        assert r.status_code == 200
        body = r.json()
        assert body.get("schema_version") == _daily_brief_module.SCHEMA_VERSION, (
            f"Expected schema_version={_daily_brief_module.SCHEMA_VERSION}, "
            f"got {body.get('schema_version')}"
        )
    finally:
        _teardown()


def test_ac1_schema_version_tracks_constant_when_bumped():
    """AC1: If SCHEMA_VERSION is bumped, the endpoint reports the new value."""
    client, _ = _make_auth_client()
    bumped_brief = {**_FAKE_BRIEF, "schema_version": 99}
    try:
        with patch("backend.main.build_brief", return_value=bumped_brief), \
             patch.object(_daily_brief_module, "SCHEMA_VERSION", 99):
            r = client.get("/api/brief/today")
        assert r.status_code == 200
        body = r.json()
        # The endpoint must NOT override schema_version with a hardcoded literal;
        # it must pass through whatever build_brief (and thus SCHEMA_VERSION) set.
        assert body.get("schema_version") == 99, (
            f"Expected schema_version=99 (tracking constant), got {body.get('schema_version')}"
        )
    finally:
        _teardown()


# ── AC2: No literal 3 override in get_brief_today source ─────────────────────

def test_ac2_no_hardcoded_schema_version_assignment():
    """AC2: get_brief_today does not assign brief['schema_version'] = <literal int>."""
    import backend.main as main_module

    func = getattr(main_module, "get_brief_today", None)
    assert func is not None, "get_brief_today not found in backend.main"

    source = inspect.getsource(func)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # Look for assignments of the form: brief["schema_version"] = <literal>
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            slice_node = target.slice
            if isinstance(slice_node, ast.Constant) and slice_node.value == "schema_version":
                if isinstance(node.value, ast.Constant):
                    raise AssertionError(
                        f"get_brief_today hardcodes brief['schema_version'] = "
                        f"{node.value.value!r}. Use daily_brief.SCHEMA_VERSION or "
                        "drop the override (build_brief already sets it)."
                    )
