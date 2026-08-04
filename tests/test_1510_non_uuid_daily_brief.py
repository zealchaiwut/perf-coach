"""Tests for issue #1510: consistent non-UUID user_id handling in daily_brief.

Acceptance criteria:
- AC1: _build_highlights_md with a non-UUID user_id returns "" (no raise)
- AC2: _assemble_recent_wrap with a non-UUID user_id returns a valid wrap dict
        with highlights_md="" instead of raising ValueError
- AC3: build_brief with a synthetic user_id (e.g. "user-id-1") does not raise
- AC4: _build_highlights_md with a valid UUID works normally (regression)
"""
from __future__ import annotations

import importlib
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def _svc():
    import backend.services.daily_brief as m
    importlib.reload(m)
    return m


@pytest.fixture(scope="module")
def svc():
    return _svc()


# ── AC1: _build_highlights_md returns "" for non-UUID user_id ─────────────────

def test_build_highlights_md_non_uuid_returns_empty_string(svc):
    """AC1: _build_highlights_md("user-id-1", date) returns '' without raising."""
    result = svc._build_highlights_md("user-id-1", date(2026, 7, 17))
    assert result == ""


def test_build_highlights_md_non_uuid_variants_do_not_raise(svc):
    """AC1: Various non-UUID string formats return '' without raising."""
    for bad_id in ["user-id-1", "synthetic", "test-user", "", "not-a-uuid"]:
        result = svc._build_highlights_md(bad_id, date(2026, 7, 17))
        assert result == "", f"Expected '' for user_id={bad_id!r}, got {result!r}"


# ── AC2: _assemble_recent_wrap works with non-UUID user_id ───────────────────

def test_assemble_recent_wrap_non_uuid_returns_valid_dict(svc):
    """AC2: _assemble_recent_wrap with synthetic user_id returns valid dict, no raise."""
    fake_load = {"ctl": 40.0, "atl": 36.0, "tsb": 4.0}

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.execute.return_value.fetchall.return_value = []

    with patch("backend.services.daily_brief.Session", return_value=mock_session), \
         patch("backend.services.daily_brief.current_load", return_value=fake_load):
        result = svc._assemble_recent_wrap("user-id-1", date(2026, 7, 17))

    required_keys = {"window_days", "sessions_planned", "sessions_completed",
                     "adherence", "load_trend", "highlights_md"}
    assert required_keys.issubset(set(result.keys()))
    assert result["highlights_md"] == ""
    assert result["adherence"] == 0.0
    assert result["sessions_planned"] == 0


# ── AC3: build_brief with synthetic user_id does not raise ───────────────────

_FAKE_PLAN_EMPTY = {"planned": False, "sessions": [], "plan_date": "2026-07-17"}
_FAKE_FORM = {
    "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
    "ramp": 0.5, "flags": {"guardrail_state": "ok"},
    "interpretation": "Neutral", "acwr": 0.95,
}
_FAKE_WRAP = {
    "window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
    "adherence": 0.0, "load_trend": 0.0, "highlights_md": "",
}
_FAKE_WEIGHT = {
    "current_kg": None, "trend_7d": None, "trend_28d": None,
    "target_kg": None, "target_date": None, "pace_kg_per_week": None,
    "on_track": None, "projection_date": None,
}


def test_build_brief_synthetic_user_id_does_not_raise(svc):
    """AC3: build_brief with synthetic 'user-id-1' returns a dict without raising."""
    with patch.object(svc, "_get_plan_for_date", return_value=_FAKE_PLAN_EMPTY), \
         patch.object(svc, "_assemble_form", return_value=_FAKE_FORM), \
         patch.object(svc, "_assemble_recent_wrap", return_value=_FAKE_WRAP), \
         patch.object(svc, "_assemble_weight", return_value=_FAKE_WEIGHT), \
         patch.object(svc, "_assemble_advisories", return_value=[]):
        result = svc.build_brief("user-id-1", date(2026, 7, 17))

    assert isinstance(result, dict)
    assert result["schema_version"] == 3


# ── AC4: _build_highlights_md works normally with a valid UUID ────────────────

def test_build_highlights_md_valid_uuid_calls_through(svc):
    """AC4: _build_highlights_md with a valid UUID proceeds to DB queries (regression)."""
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for_date = date(2026, 7, 17)

    fake_load = {"ctl": 42.0, "atl": 38.0, "tsb": 4.0, "acwr": None}
    fake_guardrail = {"guardrail_state": "ok", "acwr_state": "green", "stressors_ramping": False}

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.all.return_value = []

    with patch("backend.services.daily_brief.Session", return_value=mock_session), \
         patch("backend.services.daily_brief.current_load", return_value=fake_load), \
         patch("backend.services.daily_brief.get_guardrail_result", return_value=fake_guardrail), \
         patch(
             "backend.services.weekly_summary_facts.assemble_facts",
             return_value={},
         ), \
         patch(
             "backend.services.weekly_summary_facts.build_fallback_narrative",
             return_value="Good week.",
         ):
        result = svc._build_highlights_md(uid, for_date)

    assert isinstance(result, str)
