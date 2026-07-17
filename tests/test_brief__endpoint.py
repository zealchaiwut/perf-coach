"""Tests for issue #1498: GET /api/brief/today — authenticated daily brief endpoint.

AC coverage:
- AC1: GET /api/brief/today returns HTTP 200 with valid JSON when authenticated
- AC2: Unauthenticated requests receive HTTP 401 or 403
- AC3: Response body contains schema_version: 3 and correct shape
- AC4: Response for_date equals today's date in Asia/Bangkok timezone
- AC5: Endpoint calls build_brief() directly (no worker dependency)
- AC6: Route registered in backend/main.py using resolve_user auth guard
- AC7: Response body contains keys form, weight, advisories, and week_plan
"""
from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.auth import create_session_cookie, COOKIE_NAME
from backend.main import app, resolve_user

_BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
_USER_ID = "00000000-0000-0000-0000-000000001498"

_FAKE_BRIEF = {
    "schema_version": 2,
    "for_date": "2026-07-17",
    "generated_at": "2026-07-17T08:00:00+07:00",
    "today": {
        "date": "2026-07-17",
        "session_type": "run",
        "planned": True,
        "intensity": "easy",
        "duration_min": 50,
        "notes": None,
    },
    "tomorrow": {
        "date": "2026-07-18",
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
    "advisories": [
        {"key": "low_run_volume", "severity": "info", "text": "Consider more easy mileage."},
    ],
    "actions": [],
}


def _make_mock_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_auth_client():
    mock_user = _make_mock_user()

    async def _fake_resolve_user():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve_user
    token = create_session_cookie(_USER_ID, time.time())
    client = TestClient(app, cookies={COOKIE_NAME: token}, raise_server_exceptions=False)
    return client, mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


# ── AC1: Authenticated request returns 200 ────────────────────────────────────

def test_ac1_authenticated_returns_200():
    """AC1: GET /api/brief/today returns 200 with JSON body when authenticated."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    finally:
        _teardown()


def test_ac1_response_is_valid_json():
    """AC1: Response body is valid JSON."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)
    finally:
        _teardown()


# ── AC2: Unauthenticated requests get 401 or 403 ─────────────────────────────

def test_ac2_no_cookie_returns_401():
    """AC2: Request without session cookie returns 401."""
    app.dependency_overrides.pop(resolve_user, None)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/brief/today")
    assert r.status_code in (401, 403), (
        f"Expected 401 or 403 for unauthenticated request, got {r.status_code}"
    )


def test_ac2_unauthenticated_returns_json_error():
    """AC2: Unauthenticated response has error detail payload."""
    app.dependency_overrides.pop(resolve_user, None)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/brief/today")
    assert r.status_code in (401, 403)
    body = r.json()
    assert "detail" in body, f"Expected 'detail' in error body, got: {body}"


# ── AC3: Response schema_version is 3 ────────────────────────────────────────

def test_ac3_response_schema_version_is_3():
    """AC3: Response body contains schema_version: 3."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        assert r.status_code == 200
        body = r.json()
        assert body.get("schema_version") == 3, (
            f"Expected schema_version 3, got {body.get('schema_version')}"
        )
    finally:
        _teardown()


def test_ac3_response_has_for_date():
    """AC3: Response body contains for_date string."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert "for_date" in body
        assert isinstance(body["for_date"], str)
    finally:
        _teardown()


# ── AC4: for_date matches Bangkok today ──────────────────────────────────────

def test_ac4_for_date_matches_bangkok_today():
    """AC4: for_date in response equals today's date in Asia/Bangkok timezone."""
    bangkok_today = datetime.now(_BANGKOK_TZ).date().isoformat()
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value={
            **_FAKE_BRIEF,
            "for_date": bangkok_today,
        }):
            r = client.get("/api/brief/today")
        body = r.json()
        assert body["for_date"] == bangkok_today, (
            f"Expected for_date={bangkok_today!r}, got {body['for_date']!r}"
        )
    finally:
        _teardown()


def test_ac4_for_date_is_iso_date_string():
    """AC4: for_date is a valid ISO 8601 date string (YYYY-MM-DD)."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        from datetime import date as _date
        _date.fromisoformat(body["for_date"])
    finally:
        _teardown()


# ── AC5: Endpoint calls build_brief() — no worker needed ─────────────────────

def test_ac5_endpoint_calls_build_brief_directly():
    """AC5: Endpoint calls build_brief() directly, not a worker endpoint."""
    client, mock_user = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)) as mock_bb:
            r = client.get("/api/brief/today")
        assert r.status_code == 200
        mock_bb.assert_called_once()
    finally:
        _teardown()


def test_ac5_build_brief_called_with_user_id_and_today():
    """AC5: build_brief() is called with the session user's ID and Bangkok today."""
    bangkok_today = datetime.now(_BANGKOK_TZ).date()
    client, mock_user = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)) as mock_bb:
            r = client.get("/api/brief/today")
        assert r.status_code == 200
        args, kwargs = mock_bb.call_args
        assert args[0] == mock_user.id or kwargs.get("user_id") == mock_user.id
        called_date = args[1] if len(args) > 1 else kwargs.get("for_date")
        assert called_date == bangkok_today, (
            f"Expected date {bangkok_today}, got {called_date}"
        )
    finally:
        _teardown()


# ── AC6: Route registered in main.py with resolve_user ───────────────────────

def test_ac6_route_is_registered_in_main():
    """AC6: GET /api/brief/today route exists in the FastAPI app."""
    routes = {r.path: r for r in app.routes if hasattr(r, "path")}
    assert "/api/brief/today" in routes, (
        f"/api/brief/today not found in routes: {list(routes.keys())}"
    )


def test_ac6_route_uses_get_method():
    """AC6: The route accepts GET requests."""
    routes = {r.path: r for r in app.routes if hasattr(r, "path")}
    brief_route = routes.get("/api/brief/today")
    assert brief_route is not None
    assert "GET" in brief_route.methods, (
        f"Expected GET method, got {brief_route.methods}"
    )


# ── AC7: Response body contains required keys ─────────────────────────────────

def test_ac7_response_contains_form_key():
    """AC7: Response body contains 'form' key."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert "form" in body, f"Missing 'form' key in response: {list(body.keys())}"
    finally:
        _teardown()


def test_ac7_response_contains_weight_key():
    """AC7: Response body contains 'weight' key."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert "weight" in body, f"Missing 'weight' key in response: {list(body.keys())}"
    finally:
        _teardown()


def test_ac7_response_contains_advisories_key():
    """AC7: Response body contains 'advisories' key as a list."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert "advisories" in body, f"Missing 'advisories' key in response: {list(body.keys())}"
        assert isinstance(body["advisories"], list)
    finally:
        _teardown()


def test_ac7_response_contains_week_plan_key():
    """AC7: Response body contains 'week_plan' key (SCHEMA_VERSION 3 addition)."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert "week_plan" in body, f"Missing 'week_plan' key in response: {list(body.keys())}"
    finally:
        _teardown()


def test_ac7_all_required_keys_present():
    """AC7: Response body contains all required top-level keys."""
    required = {"form", "weight", "advisories", "week_plan"}
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        missing = required - set(body.keys())
        assert not missing, f"Missing required keys: {missing}"
    finally:
        _teardown()


def test_ac7_week_plan_is_dict():
    """AC7: week_plan value is a dict (same shape as the weekly wrap data)."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert isinstance(body.get("week_plan"), dict), (
            f"Expected week_plan to be a dict, got {type(body.get('week_plan'))}"
        )
    finally:
        _teardown()
