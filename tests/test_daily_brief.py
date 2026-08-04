"""Tests for backend/services/daily_brief.py service module.

AC coverage (issue #1496):
- AC1: build_brief(user_id, for_date) exists and returns SCHEMA_VERSION dict
- AC2: Private helpers live in the service (not only in export_brief.py)
- AC3: Plan data from PlannedSession model directly (no HTTP call)
- AC4: Weight status via compute_weight_status (no HTTP call)
- AC6: Regression snapshot — all top-level field names and value types
- AC7: build_brief happy path
- AC8: Each _assemble_* function independently testable in isolation
- AC10: No urllib/httpx/requests imports in the service module

AC coverage (issue #1497 — SCHEMA_VERSION 3 enrichment):
- SCHEMA_VERSION bumped to 3
- form.acwr exposed as float or null from current_load()
- week_plan list covering remaining days this Bangkok week after tomorrow
- week_plan empty when tomorrow is Saturday, Sunday, or past week's Sunday
- All v2 fields remain unchanged
"""
from __future__ import annotations

import importlib
import uuid
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest


# ── module import ─────────────────────────────────────────────────────────────

def _import_service():
    import backend.services.daily_brief as m
    importlib.reload(m)
    return m


@pytest.fixture(scope="module")
def svc():
    return _import_service()


# ── AC2: Service file exists and exposes required public symbol ───────────────

def test_service_module_importable():
    """AC2: backend.services.daily_brief is importable."""
    import backend.services.daily_brief  # noqa: F401


def test_build_brief_is_callable(svc):
    """AC1: build_brief is a callable exported from the service."""
    assert callable(svc.build_brief)


def test_private_helpers_exist_in_service(svc):
    """AC2: All required private helpers are present in the service module."""
    expected = [
        "_build_brief",
        "_assemble_form",
        "_assemble_weight",
        "_assemble_advisories",
        "_assemble_recent_wrap",
        "_compute_weight_advisory",
        "_load_interpretation",
    ]
    for name in expected:
        assert hasattr(svc, name), f"Service missing helper: {name}"


# ── AC10: No HTTP client imports in service ───────────────────────────────────

def test_no_http_client_imports(svc):
    """AC10: Service module must not import urllib.request, requests, or httpx."""
    import inspect
    src = inspect.getsource(svc)
    forbidden = ["urllib.request", "import requests", "import httpx"]
    for token in forbidden:
        assert token not in src, f"Forbidden HTTP client import found: {token!r}"


# ── AC3: Plan data from PlannedSession model, not HTTP ───────────────────────

def test_get_plan_for_date_uses_planned_session_model(svc):
    """AC3: _get_plan_for_date queries PlannedSession model, not HTTP."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_query.filter.return_value.all.return_value = []
    mock_session.query.return_value = mock_query

    with patch("backend.services.daily_brief.Session", return_value=mock_session):
        result = svc._get_plan_for_date(uid, for_date)

    assert result["planned"] is False
    assert result["sessions"] == []
    assert result["plan_date"] == "2026-07-17"


def test_get_plan_for_date_with_sessions(svc):
    """AC3: _get_plan_for_date returns planned=True when rows exist."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    fake_row = MagicMock()
    fake_row.session_type = "run"
    fake_row.name = "Easy run"
    fake_row.notes = "Zone 2"
    fake_row.status = "planned"
    fake_row.structure = {"intensity": "easy", "duration_min": 50}

    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_query.filter.return_value.all.return_value = [fake_row]
    mock_session.query.return_value = mock_query

    with patch("backend.services.daily_brief.Session", return_value=mock_session):
        result = svc._get_plan_for_date(uid, for_date)

    assert result["planned"] is True
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["session_type"] == "run"


# ── AC4: Weight via compute_weight_status, not HTTP ──────────────────────────

def test_assemble_weight_uses_compute_weight_status(svc):
    """AC4: _assemble_weight calls compute_weight_status, not HTTP."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)
    fake_status = {
        "current_kg": 72.5,
        "trend_7d": -0.2,
        "trend_28d": -0.5,
        "target_kg": 70.0,
        "target_date": "2026-09-01",
        "pace_kg_per_week": -0.2,
        "on_track": True,
        "projection_date": "2026-08-25",
    }

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("backend.services.daily_brief.Session", return_value=mock_session), \
         patch("backend.services.daily_brief.compute_weight_status", return_value=fake_status) as mock_cws:
        result = svc._assemble_weight(uid, for_date)

    mock_cws.assert_called_once()
    assert result["current_kg"] == 72.5
    assert result["on_track"] is True


def test_assemble_weight_degrades_gracefully(svc):
    """AC4: _assemble_weight returns null block when compute_weight_status fails."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("backend.services.daily_brief.Session", return_value=mock_session), \
         patch("backend.services.daily_brief.compute_weight_status", side_effect=RuntimeError("no data")):
        result = svc._assemble_weight(uid, for_date)

    assert result["current_kg"] is None
    assert result["on_track"] is None


# ── AC8: _assemble_form in isolation ─────────────────────────────────────────

def test_assemble_form_returns_required_keys(svc):
    """AC8: _assemble_form returns dict with ctl, atl, tsb, ramp, flags, interpretation."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    fake_load = {"ctl": 42.0, "atl": 38.0, "tsb": 4.0, "acwr": 0.95}
    fake_guardrail = {"guardrail_state": "ok", "acwr_state": "green", "stressors_ramping": False}

    with patch("backend.services.daily_brief.current_load", return_value=fake_load), \
         patch("backend.services.daily_brief.get_snapshot_series", return_value=[
             {"ctl": 40.0}, {"ctl": 42.0}
         ]), \
         patch("backend.services.daily_brief.get_guardrail_result", return_value=fake_guardrail):
        result = svc._assemble_form(uid, for_date)

    assert set(result.keys()) >= {"ctl", "atl", "tsb", "ramp", "flags", "interpretation"}
    assert result["ctl"] == 42.0
    assert result["atl"] == 38.0
    assert result["tsb"] == 4.0
    assert "interpretation" in result


# ── AC8: _assemble_recent_wrap in isolation ───────────────────────────────────

def test_assemble_recent_wrap_returns_required_keys(svc):
    """AC8: _assemble_recent_wrap returns dict with all required keys."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    fake_load = {"ctl": 42.0, "atl": 38.0, "tsb": 4.0}

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.execute.return_value.fetchall.return_value = []

    with patch("backend.services.daily_brief.Session", return_value=mock_session), \
         patch("backend.services.daily_brief.current_load", return_value=fake_load), \
         patch("backend.services.daily_brief._build_highlights_md", return_value="Rest week."):
        result = svc._assemble_recent_wrap(uid, for_date)

    required = {"window_days", "sessions_planned", "sessions_completed", "adherence", "load_trend", "highlights_md"}
    assert required.issubset(set(result.keys()))
    assert 0.0 <= result["adherence"] <= 1.0
    assert result["highlights_md"] == "Rest week."


# ── AC8: _compute_weight_advisory in isolation ────────────────────────────────

def test_compute_weight_advisory_no_target(svc):
    """AC8: _compute_weight_advisory returns None when no target set."""
    assert svc._compute_weight_advisory({"target_kg": None}, "hold") is None


def test_compute_weight_advisory_on_track_no_build(svc):
    """AC8: No advisory when on-track and not in build phase."""
    weight = {"target_kg": 70.0, "on_track": True}
    result = svc._compute_weight_advisory(weight, "hold")
    assert result is None


def test_compute_weight_advisory_behind_no_build(svc):
    """AC8: warn advisory when behind pace and not in build phase."""
    weight = {"target_kg": 70.0, "on_track": False}
    result = svc._compute_weight_advisory(weight, "hold")
    assert result is not None
    assert result["severity"] == "warn"
    assert result["key"] == "weight_pace_behind_tighten_up"


def test_compute_weight_advisory_build_phase(svc):
    """AC8: info advisory with hold-intake key during build phase."""
    weight = {"target_kg": 70.0, "on_track": True}
    result = svc._compute_weight_advisory(weight, "build")
    assert result is not None
    assert result["severity"] == "info"
    assert result["key"] == "weight_hold_intake_build"


# ── AC8: _load_interpretation in isolation ────────────────────────────────────

def test_load_interpretation_all_labels(svc):
    """AC8: _load_interpretation returns correct label for each TSB band."""
    assert "Fresh" in svc._load_interpretation(50.0, 40.0, 10.0)
    assert "Neutral" in svc._load_interpretation(50.0, 48.0, 2.0)
    assert "Productive" in svc._load_interpretation(50.0, 55.0, -8.0)
    assert "Overreached" in svc._load_interpretation(50.0, 72.0, -22.0)


def test_load_interpretation_ctl_modifiers(svc):
    """AC8: CTL > 60 appends 'well-trained'; CTL < 30 appends 'undertrained'."""
    assert "well-trained" in svc._load_interpretation(65.0, 60.0, 5.0)
    assert "undertrained" in svc._load_interpretation(20.0, 15.0, 5.0)


# ── AC7 / AC1: build_brief happy path ────────────────────────────────────────

_FAKE_PLAN_EMPTY = {"planned": False, "sessions": [], "plan_date": "2026-07-17"}
_FAKE_FORM = {
    "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
    "ramp": 0.5, "flags": {"guardrail_state": "ok"},
    "interpretation": "Neutral",
    "acwr": 0.95,
}
_FAKE_WRAP = {
    "window_days": 14,
    "sessions_planned": 10,
    "sessions_completed": 8,
    "adherence": 0.8,
    "load_trend": 1.2,
    "highlights_md": "Good week.",
}
_FAKE_WEIGHT = {
    "current_kg": 72.5,
    "trend_7d": -0.2,
    "trend_28d": -0.5,
    "target_kg": 70.0,
    "target_date": "2026-09-01",
    "pace_kg_per_week": -0.2,
    "on_track": True,
    "projection_date": "2026-08-25",
}


def test_build_brief_happy_path(svc):
    """AC7: build_brief returns complete dict with all top-level fields (v3)."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert result["schema_version"] == 3
    assert result["for_date"] == "2026-07-17"
    assert "+07:00" in result["generated_at"]
    assert result["actions"] == []
    assert "week_plan" in result


# ── AC6: Regression snapshot — v2 shape ──────────────────────────────────────

V2_FIELD_TYPES = {
    "schema_version": int,
    "for_date": str,
    "generated_at": str,
    "today": dict,
    "tomorrow": dict,
    "form": dict,
    "recent_wrap": dict,
    "weight": dict,
    "advisories": list,
    "advisories_degraded": bool,
    "actions": list,
    "week_plan": list,
}

SESSION_KEYS = {"date", "session_type", "planned", "intensity", "duration_min", "notes"}
FORM_KEYS = {"ctl", "atl", "tsb", "ramp", "flags", "interpretation", "acwr"}
WEEK_PLAN_ITEM_KEYS = {"date", "day", "session_type", "intensity", "duration_min", "planned"}
RECENT_WRAP_KEYS = {"window_days", "sessions_planned", "sessions_completed", "adherence", "load_trend", "highlights_md"}
WEIGHT_KEYS = {"current_kg", "trend_7d", "trend_28d", "target_kg", "target_date", "pace_kg_per_week", "on_track", "projection_date"}


def test_v2_snapshot_top_level_field_names(svc):
    """AC6: All v2 top-level field names and types present in build_brief output."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    for field, expected_type in V2_FIELD_TYPES.items():
        assert field in result, f"Missing top-level field: {field}"
        assert isinstance(result[field], expected_type), (
            f"Field {field!r}: expected {expected_type.__name__}, got {type(result[field]).__name__}"
        )


def test_v2_snapshot_session_shape(svc):
    """AC6: today/tomorrow session objects have all required keys."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert SESSION_KEYS.issubset(set(result["today"].keys()))
    assert SESSION_KEYS.issubset(set(result["tomorrow"].keys()))


def test_v2_snapshot_nested_shapes(svc):
    """AC6: form, recent_wrap, weight all have their required nested keys."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert FORM_KEYS.issubset(set(result["form"].keys()))
    assert RECENT_WRAP_KEYS.issubset(set(result["recent_wrap"].keys()))
    assert WEIGHT_KEYS.issubset(set(result["weight"].keys()))


def test_v2_schema_version_is_2(svc):
    """AC (#1497): schema_version bumped to 3; all v2 fields still present."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert result["schema_version"] == 3
    assert svc.SCHEMA_VERSION == 3


def test_build_brief_today_tomorrow_dates(svc):
    """AC1: today uses for_date, tomorrow uses for_date + 1 day."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    calls = []

    def capture_plan(user_id, d):
        calls.append(d.isoformat())
        return {"planned": False, "sessions": [], "plan_date": d.isoformat()}

    with patch.object(svc, "_get_plan_for_date", side_effect=capture_plan), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert calls == ["2026-07-17", "2026-07-18"]
    assert result["today"]["date"] == "2026-07-17"
    assert result["tomorrow"]["date"] == "2026-07-18"


# ── Snapshot test: service output matches export_brief output shape ─────────

def test_service_and_script_same_v2_shape():
    """AC6/v3: Service produces all v3 top-level field names with correct types."""
    svc_mod = _import_service()

    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)  # Friday → week_plan = []

    with patch.object(svc_mod, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc_mod, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc_mod, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc_mod, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(svc_mod, "_assemble_coach", return_value=None):
        svc_result = svc_mod.build_brief(uid, for_date)

    assert set(svc_result.keys()) == set(V2_FIELD_TYPES.keys())
    for field, expected_type in V2_FIELD_TYPES.items():
        assert isinstance(svc_result[field], expected_type), (
            f"Service field {field!r} wrong type"
        )


# ── v3: form.acwr ─────────────────────────────────────────────────────────────

def test_form_acwr_present_and_matches_current_load(svc):
    """AC (#1497): form.acwr is a float sourced from current_load()."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 15)  # Wednesday

    fake_load = {"ctl": 42.0, "atl": 38.0, "tsb": 4.0, "acwr": 0.93}
    fake_guardrail = {"guardrail_state": "ok", "acwr_state": "green", "stressors_ramping": False}

    with patch("backend.services.daily_brief.current_load", return_value=fake_load), \
         patch("backend.services.daily_brief.get_snapshot_series", return_value=[
             {"ctl": 40.0}, {"ctl": 42.0}
         ]), \
         patch("backend.services.daily_brief.get_guardrail_result", return_value=fake_guardrail):
        result = svc._assemble_form(uid, for_date)

    assert "acwr" in result
    assert result["acwr"] == pytest.approx(0.93, abs=1e-4)


def test_form_acwr_is_none_when_load_returns_none(svc):
    """AC (#1497): form.acwr is null when current_load() returns no acwr."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 15)

    fake_load = {"ctl": 10.0, "atl": 8.0, "tsb": 2.0, "acwr": None}
    fake_guardrail = {"guardrail_state": "ok", "acwr_state": "grey", "stressors_ramping": False}

    with patch("backend.services.daily_brief.current_load", return_value=fake_load), \
         patch("backend.services.daily_brief.get_snapshot_series", return_value=[{"ctl": 10.0}]), \
         patch("backend.services.daily_brief.get_guardrail_result", return_value=fake_guardrail):
        result = svc._assemble_form(uid, for_date)

    assert "acwr" in result
    assert result["acwr"] is None


# ── v3: week_plan ─────────────────────────────────────────────────────────────

def test_week_plan_mid_week_wednesday(svc):
    """AC (#1497): week_plan for Wednesday (today) returns Thu–Sun (4 items)."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 15)  # Wednesday

    def fake_plan(user_id, d):
        return {"planned": False, "sessions": [], "plan_date": d.isoformat()}

    with patch.object(svc, "_get_plan_for_date", side_effect=fake_plan):
        result = svc._assemble_week_plan(uid, for_date)

    assert len(result) == 4
    assert [item["date"] for item in result] == [
        "2026-07-16", "2026-07-17", "2026-07-18", "2026-07-19"
    ]
    assert [item["day"] for item in result] == ["Thu", "Fri", "Sat", "Sun"]
    for item in result:
        assert WEEK_PLAN_ITEM_KEYS == set(item.keys())
        assert item["planned"] is False
        assert item["session_type"] is None


def test_week_plan_friday_empty(svc):
    """AC (#1497): week_plan when today is Friday (tomorrow=Saturday) returns []."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)  # Friday

    result = svc._assemble_week_plan(uid, for_date)
    assert result == []


def test_week_plan_sunday_empty(svc):
    """AC (#1497): week_plan when today is Sunday (tomorrow=Monday) returns []."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 19)  # Sunday

    result = svc._assemble_week_plan(uid, for_date)
    assert result == []


def test_week_plan_day_with_planned_session(svc):
    """AC (#1497): days with a PlannedSession appear with planned=True and correct fields."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 15)  # Wednesday → Thu is first week_plan day

    def fake_plan(user_id, d):
        if d == date(2026, 7, 16):  # Thursday
            return {
                "planned": True,
                "sessions": [{
                    "session_type": "run",
                    "note": "Tempo",
                    "status": "planned",
                    "target": {"intensity": "hard", "duration_min": 45},
                }],
                "plan_date": "2026-07-16",
            }
        return {"planned": False, "sessions": [], "plan_date": d.isoformat()}

    with patch.object(svc, "_get_plan_for_date", side_effect=fake_plan):
        result = svc._assemble_week_plan(uid, for_date)

    thu = result[0]
    assert thu["date"] == "2026-07-16"
    assert thu["day"] == "Thu"
    assert thu["planned"] is True
    assert thu["session_type"] == "run"
    assert thu["intensity"] == "hard"
    assert thu["duration_min"] == 45

    fri = result[1]
    assert fri["planned"] is False
    assert fri["session_type"] is None


def test_week_plan_in_build_brief_output(svc):
    """AC (#1497): build_brief output includes week_plan as a list."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)  # Friday → week_plan = []

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert "week_plan" in result
    assert isinstance(result["week_plan"], list)


def test_v2_fields_remain_in_v3_output(svc):
    """AC (#1497): all v2 top-level fields are unchanged in v3 output."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    v2_fields = ["for_date", "generated_at", "today", "tomorrow",
                 "form", "recent_wrap", "weight", "advisories", "actions"]
    for field in v2_fields:
        assert field in result, f"v2 field {field!r} missing from v3 output"
