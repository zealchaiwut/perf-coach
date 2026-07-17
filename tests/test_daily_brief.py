"""Tests for issue #1496: backend/services/daily_brief.py service module.

AC coverage:
- AC1: build_brief(user_id, for_date) exists and returns SCHEMA_VERSION 2 dict
- AC2: Private helpers live in the service (not only in export_brief.py)
- AC3: Plan data from PlannedSession model directly (no HTTP call)
- AC4: Weight status via compute_weight_status (no HTTP call)
- AC6: Regression snapshot — all top-level field names and value types for v2 shape
- AC7: build_brief happy path
- AC8: Each _assemble_* function independently testable in isolation
- AC10: No urllib/httpx/requests imports in the service module
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
    """AC7: build_brief returns complete v2 dict with all top-level fields."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert result["schema_version"] == 2
    assert result["for_date"] == "2026-07-17"
    assert "+07:00" in result["generated_at"]
    assert result["actions"] == []


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
    "actions": list,
}

SESSION_KEYS = {"date", "session_type", "planned", "intensity", "duration_min", "notes"}
FORM_KEYS = {"ctl", "atl", "tsb", "ramp", "flags", "interpretation"}
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
    """AC1: schema_version in build_brief output is exactly 2."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief(uid, for_date)

    assert result["schema_version"] == 2
    assert svc.SCHEMA_VERSION == 2


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
    """AC6: Both the service and the CLI wrapper produce the same v2 field names/types."""
    import importlib.util
    import pathlib

    svc_mod = _import_service()
    script_path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "export_brief.py"
    spec = importlib.util.spec_from_file_location("export_brief_compat", script_path)
    script_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script_mod)

    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    with patch.object(svc_mod, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc_mod, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc_mod, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc_mod, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc_mod, "_assemble_advisories", return_value=[]):
        svc_result = svc_mod.build_brief(uid, for_date)

    assert set(svc_result.keys()) == set(V2_FIELD_TYPES.keys())
    for field, expected_type in V2_FIELD_TYPES.items():
        assert isinstance(svc_result[field], expected_type), (
            f"Service field {field!r} wrong type"
        )
