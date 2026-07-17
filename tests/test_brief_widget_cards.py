"""Tests for issue #1499: Daily Brief widget cards on the Home grid.

AC coverage (backend / data-shape assertions only; JS rendering is UAT):
- AC2/AC3: form block has ctl, atl, tsb, flags.acwr_state, interpretation
- AC4: ACWR pill states (flags.acwr_state values are 'ok', 'caution', 'high')
- AC5: week_plan.days ordered today-first; days have day/planned/session_type/duration_min
- AC6: advisories list items have severity and text fields
- AC8: GET /api/brief/today degrades gracefully (returns 200 even on empty data)
- AC9: A single fetch suffices — endpoint exists and returns all three card payloads
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import create_session_cookie, COOKIE_NAME
from backend.main import app, resolve_user

_USER_ID = "00000000-0000-0000-0000-000000001499"

_FAKE_BRIEF_V3 = {
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
        "ctl": 42.0,
        "atl": 38.0,
        "tsb": 4.0,
        "ramp": 1.2,
        "flags": {"guardrail_state": "ok", "acwr_state": "ok", "stressors_ramping": False},
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
        {"key": "low_run_volume", "severity": "warn", "text": "Consider more easy mileage."},
        {"key": "hrv_drop", "severity": "info", "text": "HRV trending down — rest well tonight."},
    ],
    "actions": [],
}

_FAKE_WEEK_PLAN = {
    "days": [
        {"date": "2026-07-17", "day": "Thu", "planned": True, "session_type": "run", "duration_min": 50},
        {"date": "2026-07-18", "day": "Fri", "planned": False, "session_type": None, "duration_min": None},
        {"date": "2026-07-19", "day": "Sat", "planned": True, "session_type": "strength", "duration_min": 60},
        {"date": "2026-07-20", "day": "Sun", "planned": False, "session_type": None, "duration_min": None},
        {"date": "2026-07-21", "day": "Mon", "planned": True, "session_type": "run", "duration_min": 45},
        {"date": "2026-07-22", "day": "Tue", "planned": False, "session_type": None, "duration_min": None},
        {"date": "2026-07-23", "day": "Wed", "planned": True, "session_type": "run", "duration_min": 60},
    ]
}


def _make_auth_client():
    mock_user = MagicMock()
    mock_user.id = _USER_ID

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    token = create_session_cookie(_USER_ID, time.time())
    client = TestClient(app, cookies={COOKIE_NAME: token}, raise_server_exceptions=False)
    return client, mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


# ── AC2/AC3: Form card data shape ────────────────────────────────────────────

def test_form_block_has_ctl_atl_tsb():
    """AC3: form block contains ctl, atl, tsb numeric values."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)):
            r = client.get("/api/brief/today")
        body = r.json()
        form = body["form"]
        assert "ctl" in form and isinstance(form["ctl"], (int, float))
        assert "atl" in form and isinstance(form["atl"], (int, float))
        assert "tsb" in form and isinstance(form["tsb"], (int, float))
    finally:
        _teardown()


def test_form_block_has_interpretation():
    """AC3: form block contains interpretation string."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert isinstance(body["form"].get("interpretation"), str)
    finally:
        _teardown()


def test_form_block_has_flags_with_acwr_state():
    """AC4: form.flags.acwr_state is present for ACWR pill rendering."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)):
            r = client.get("/api/brief/today")
        body = r.json()
        flags = body["form"].get("flags", {})
        assert "acwr_state" in flags, f"flags missing acwr_state: {flags}"
    finally:
        _teardown()


def test_acwr_state_ok_value():
    """AC4: acwr_state='ok' is a valid value for the green pill."""
    brief = {**_FAKE_BRIEF_V3, "form": {**_FAKE_BRIEF_V3["form"],
        "flags": {**_FAKE_BRIEF_V3["form"]["flags"], "acwr_state": "ok"}}}
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=brief):
            r = client.get("/api/brief/today")
        body = r.json()
        assert body["form"]["flags"]["acwr_state"] == "ok"
    finally:
        _teardown()


def test_acwr_state_caution_value():
    """AC4: acwr_state='caution' is a valid value for the amber pill."""
    brief = {**_FAKE_BRIEF_V3, "form": {**_FAKE_BRIEF_V3["form"],
        "flags": {**_FAKE_BRIEF_V3["form"]["flags"], "acwr_state": "caution"}}}
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=brief):
            r = client.get("/api/brief/today")
        body = r.json()
        assert body["form"]["flags"]["acwr_state"] == "caution"
    finally:
        _teardown()


def test_acwr_state_high_value():
    """AC4: acwr_state='high' is a valid value for the red pill."""
    brief = {**_FAKE_BRIEF_V3, "form": {**_FAKE_BRIEF_V3["form"],
        "flags": {**_FAKE_BRIEF_V3["form"]["flags"], "acwr_state": "high"}}}
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=brief):
            r = client.get("/api/brief/today")
        body = r.json()
        assert body["form"]["flags"]["acwr_state"] == "high"
    finally:
        _teardown()


# ── AC5: week_plan structure ─────────────────────────────────────────────────

def test_week_plan_days_is_list():
    """AC5: week_plan.days is a list."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)), \
             patch("backend.main._build_week_plan", return_value=dict(_FAKE_WEEK_PLAN)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert isinstance(body["week_plan"]["days"], list)
    finally:
        _teardown()


def test_week_plan_days_have_required_fields():
    """AC5: Each day in week_plan.days has date, day, planned, session_type, duration_min."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)), \
             patch("backend.main._build_week_plan", return_value=dict(_FAKE_WEEK_PLAN)):
            r = client.get("/api/brief/today")
        body = r.json()
        for day in body["week_plan"]["days"]:
            assert "date" in day
            assert "day" in day
            assert "planned" in day
            assert "session_type" in day
            assert "duration_min" in day
    finally:
        _teardown()


def test_week_plan_first_day_is_today():
    """AC5: First day in week_plan.days matches the brief's for_date (today-first)."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)), \
             patch("backend.main._build_week_plan", return_value=dict(_FAKE_WEEK_PLAN)):
            r = client.get("/api/brief/today")
        body = r.json()
        days = body["week_plan"]["days"]
        assert len(days) >= 2
        assert days[0]["date"] == body["for_date"], (
            f"First day {days[0]['date']!r} != for_date {body['for_date']!r}"
        )
    finally:
        _teardown()


def test_week_plan_rest_days_have_planned_false():
    """AC5: Rest days in week_plan have planned=False."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)), \
             patch("backend.main._build_week_plan", return_value=dict(_FAKE_WEEK_PLAN)):
            r = client.get("/api/brief/today")
        body = r.json()
        for day in body["week_plan"]["days"]:
            if not day["planned"]:
                assert day["session_type"] is None or day["session_type"] == "rest"
    finally:
        _teardown()


# ── AC6: Advisories shape ────────────────────────────────────────────────────

def test_advisories_items_have_severity_and_text():
    """AC6: Each advisory has severity and text fields."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)):
            r = client.get("/api/brief/today")
        body = r.json()
        for adv in body["advisories"]:
            assert "severity" in adv, f"advisory missing severity: {adv}"
            assert "text" in adv, f"advisory missing text: {adv}"
    finally:
        _teardown()


def test_advisories_warn_severity_is_string():
    """AC6: severity='warn' for warning advisories."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)):
            r = client.get("/api/brief/today")
        body = r.json()
        warn_items = [a for a in body["advisories"] if a["severity"] == "warn"]
        assert len(warn_items) >= 1, "Expected at least one warn advisory in fixture"
    finally:
        _teardown()


def test_empty_advisories_returns_list():
    """AC6: Empty advisories returns empty list (card shows '(none)')."""
    brief = {**_FAKE_BRIEF_V3, "advisories": []}
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=brief):
            r = client.get("/api/brief/today")
        body = r.json()
        assert body["advisories"] == []
    finally:
        _teardown()


# ── AC8/AC9: Single-fetch completeness ────────────────────────────────────────

def test_single_fetch_returns_all_card_payloads():
    """AC9: A single GET /api/brief/today response contains all three card payloads."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert "form" in body, "Missing form (Form card payload)"
        assert "week_plan" in body, "Missing week_plan (Week Plan card payload)"
        assert "advisories" in body, "Missing advisories (Advisories card payload)"
    finally:
        _teardown()


def test_schema_version_is_3():
    """AC9: schema_version is 3 in the endpoint response."""
    client, _ = _make_auth_client()
    try:
        with patch("backend.main.build_brief", return_value=dict(_FAKE_BRIEF_V3)):
            r = client.get("/api/brief/today")
        body = r.json()
        assert body.get("schema_version") == 3
    finally:
        _teardown()
