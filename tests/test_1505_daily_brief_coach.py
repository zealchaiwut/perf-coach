"""Tests for issue #1505: Coach field in Hermes daily brief (export_brief.py).

AC coverage:
- AC10: scripts/export_brief.py gains _assemble_coach() returning a dict with
         directive (str), projection (str), and levers (list[str]) when an
         active goal exists.
- AC11: SCHEMA_VERSION bumped to 3 (from 2).
- AC12: All pre-existing top-level fields (today, tomorrow, form, recent_wrap,
         weight, advisories, actions) are present and unchanged.
- AC13: _build_brief includes top-level "coach" key when _assemble_coach
         returns a non-None dict.
- AC14: When no active goal: _assemble_coach returns None; "coach" key is
         absent (not null) from _build_brief output.

Note (#1663): After de8019f1 consolidated _build_brief into backend.services.daily_brief,
_assemble_coach no longer uses _load_goal_for_user / _build_plan_state_for_user directly;
it delegates to get_coach_payload_for_user (weekly_coach_message). Tests that previously
patched those removed helpers are repointed at get_coach_payload_for_user. Lever-pill
content tests (locked lever contains date, weight lever contains count) are removed because
_assemble_coach no longer renders lever pills — that detail moved to the service layer.
"""
from __future__ import annotations

import importlib
import importlib.util
import pathlib
from datetime import date
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"


def _import_module():
    spec = importlib.util.spec_from_file_location("export_brief", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _import_module()


_UID = "00000000-0000-0000-0000-000000000001"


def _fake_coach_payload(now_text="Hold TSS at current level.", dream_text="plan → ~1:45 by mid-Dec · now ~1:52"):
    """Minimal fake get_coach_payload_for_user return value for _assemble_coach tests."""
    return {
        "as_of": "2026-07-17",
        "source": "weekly_coach",
        "sections": {"now": now_text, "dream": dream_text},
        "nudge": {},
        "text": f"{now_text} {dream_text}",
        "chosen_preset": None,
    }


# ── AC11: SCHEMA_VERSION bumped to 3 ─────────────────────────────────────────

def test_schema_version_is_3(m):
    """AC11: SCHEMA_VERSION constant is 3 after the coach block addition."""
    assert m.SCHEMA_VERSION == 3


# ── AC10: _assemble_coach shape when goal is active ──────────────────────────

def test_assemble_coach_returns_dict_with_required_keys(m):
    """AC10: _assemble_coach returns dict with directive, projection, levers keys."""
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=_fake_coach_payload(),
    ):
        result = m._assemble_coach(_UID, date(2026, 7, 17))

    assert result is not None
    assert "directive" in result
    assert "projection" in result
    assert "levers" in result


def test_assemble_coach_directive_is_string(m):
    """AC10: directive is a non-empty string (the Now sentence)."""
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=_fake_coach_payload(now_text="Hold TSS steady this week."),
    ):
        result = m._assemble_coach(_UID, date(2026, 7, 17))

    assert isinstance(result["directive"], str)
    assert len(result["directive"]) > 0


def test_assemble_coach_projection_is_string(m):
    """AC10: projection is a non-empty one-line string."""
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=_fake_coach_payload(dream_text="plan → ~1:45 by mid-Dec · now ~1:52"),
    ):
        result = m._assemble_coach(_UID, date(2026, 7, 17))

    assert isinstance(result["projection"], str)
    assert len(result["projection"]) > 0
    assert "\n" not in result["projection"], "projection should be one line"


def test_assemble_coach_levers_is_list(m):
    """AC10: levers is a list (may be empty after de8019f1; all items are strings)."""
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=_fake_coach_payload(),
    ):
        result = m._assemble_coach(_UID, date(2026, 7, 17))

    assert isinstance(result["levers"], list)
    for item in result["levers"]:
        assert isinstance(item, str)


# ── AC14: No active goal → _assemble_coach returns None ──────────────────────

def test_assemble_coach_returns_none_when_no_goal(m):
    """AC14: _assemble_coach returns None when no coach payload is available."""
    uid = "00000000-0000-0000-0000-000000000001"
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=None,
    ):
        result = m._assemble_coach(uid, date(2026, 7, 17))
    assert result is None


# ── AC13: _build_brief includes "coach" key when goal active ─────────────────

def _patch_build_brief(coach):
    """Patch daily_brief helpers used by export_brief._build_brief."""
    from datetime import timedelta

    from backend.services import daily_brief as svc

    for_date = date(2026, 7, 17)
    fake_cache = {
        for_date + timedelta(days=i): {
            "plan_date": (for_date + timedelta(days=i)).isoformat(),
            "planned": False,
            "sessions": [],
        }
        for i in range(7)
    }
    return (
        patch.object(svc, "_get_plans_for_date_range", return_value=fake_cache),
        patch.object(svc, "_assemble_form", return_value={
            "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
            "ramp": 1.0, "flags": {}, "interpretation": "Neutral",
        }),
        patch.object(svc, "_assemble_recent_wrap", return_value={
            "window_days": 14, "sessions_planned": 8, "sessions_completed": 6,
            "adherence": 0.75, "load_trend": 0.5, "highlights_md": "Good week.",
        }),
        patch.object(svc, "_assemble_weight", return_value={"ewma": None, "entries": []}),
        patch.object(svc, "_assemble_advisories", return_value=[]),
        patch.object(svc, "_assemble_week_plan", return_value={"days": []}),
        patch.object(svc, "_assemble_coach", return_value=coach),
    )


def test_build_brief_includes_coach_when_goal_active(m):
    """AC13: 'coach' key is present in output when _assemble_coach returns a dict."""
    fake_coach = {
        "directive": "Hold TSS at 315/week until load normalises.",
        "projection": "plan → ~1:45 by mid-Dec · now ~1:52",
        "levers": ["load: locked until 31 Jul", "weight: measurement 9/14 days"],
    }
    uid = "00000000-0000-0000-0000-000000000001"
    with ExitStack() as stack:
        for p in _patch_build_brief(fake_coach):
            stack.enter_context(p)
        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", uid, None)

    assert "coach" in brief
    assert brief["coach"]["directive"] == fake_coach["directive"]
    assert brief["coach"]["projection"] == fake_coach["projection"]
    assert brief["coach"]["levers"] == fake_coach["levers"]


def test_build_brief_omits_coach_when_no_goal(m):
    """AC14: 'coach' key is absent (not null) when _assemble_coach returns None."""
    uid = "00000000-0000-0000-0000-000000000001"
    with ExitStack() as stack:
        for p in _patch_build_brief(None):
            stack.enter_context(p)
        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", uid, None)

    assert "coach" not in brief, "'coach' key must be absent, not null, when no goal"


# ── AC12: Pre-existing fields unchanged ──────────────────────────────────────

_EXISTING_KEYS = {"schema_version", "for_date", "generated_at", "today", "tomorrow",
                  "form", "recent_wrap", "advisories", "actions"}


def test_existing_brief_fields_still_present(m):
    """AC12: All pre-existing top-level fields are present regardless of coach presence."""
    fake_coach = {"directive": "Hold.", "projection": "1:45", "levers": ["load: locked"]}
    uid = "00000000-0000-0000-0000-000000000001"

    with ExitStack() as stack:
        for p in _patch_build_brief(fake_coach):
            stack.enter_context(p)
        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", uid, None)

    missing = _EXISTING_KEYS - set(brief.keys())
    assert not missing, f"Missing pre-existing fields: {missing}"


def test_existing_fields_present_without_coach_too(m):
    """AC12: Pre-existing fields are still all present when no active goal (no coach key)."""
    uid = "00000000-0000-0000-0000-000000000001"

    with ExitStack() as stack:
        for p in _patch_build_brief(None):
            stack.enter_context(p)
        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", uid, None)

    missing = _EXISTING_KEYS - set(brief.keys())
    assert not missing, f"Missing pre-existing fields: {missing}"


# ── Integration: _assemble_coach uses plan_state for directive ────────────────

def test_assemble_coach_directive_references_locked_load(m):
    """AC10: directive reflects the locked-load coaching message from the service."""
    locked_now = "Hold TSS at current level; ACWR converges by end of month."
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=_fake_coach_payload(now_text=locked_now),
    ):
        result = m._assemble_coach(_UID, date(2026, 7, 17))

    assert result is not None
    directive = result["directive"]
    assert any(kw in directive.lower() for kw in ("hold", "locked", "lock", "acwr", "converge")), \
        f"Directive doesn't reflect locked load state: {directive!r}"


def test_assemble_coach_projection_contains_times(m):
    """AC10: projection string contains the target and current-trend times."""
    dream = "plan → ~1:45 by mid-Dec · now ~1:52"
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=_fake_coach_payload(dream_text=dream),
    ):
        result = m._assemble_coach(_UID, date(2026, 7, 17))

    projection = result["projection"]
    assert "1:45" in projection or "1:52" in projection, \
        f"Projection doesn't contain expected times: {projection!r}"


def test_assemble_coach_error_returns_none(m):
    """AC10: _assemble_coach returns None (not raises) on internal error."""
    uid = "00000000-0000-0000-0000-000000000001"
    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        side_effect=RuntimeError("DB down"),
    ):
        result = m._assemble_coach(uid, date(2026, 7, 17))
    assert result is None
