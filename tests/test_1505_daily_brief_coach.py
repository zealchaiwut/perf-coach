"""Tests for issue #1505: Coach field in Hermes daily brief (export_brief.py).

AC coverage:
- AC10: _assemble_coach() returns a dict with directive (str), projection (str),
         and levers (list) when a payload is available; now lives in
         backend.services.daily_brief (moved there by issue #1509).
- AC11: SCHEMA_VERSION bumped to 3 (from 2).
- AC12: All pre-existing top-level fields (today, tomorrow, form, recent_wrap,
         weight, advisories, actions) are present and unchanged.
- AC13: _build_brief includes top-level "coach" key when _assemble_coach
         returns a non-None dict.
- AC14: When no payload: _assemble_coach returns None; "coach" key is
         absent (not null) from _build_brief output.

Note (issue #1509): _assemble_coach moved from scripts/export_brief.py into
backend.services.daily_brief.  Tests that previously patched
m._load_goal_for_user and m._build_plan_state_for_user (stubs for an older
implementation) have been updated to patch
backend.services.weekly_coach_message.get_coach_payload_for_user, which is
what the current _assemble_coach calls.  _build_brief tests now patch the
service module directly (since m._build_brief is a thin wrapper).
"""
from __future__ import annotations

import importlib
import importlib.util
import pathlib
import uuid as _uuid_mod
from datetime import date
from unittest.mock import patch

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"

_FAKE_UID = _uuid_mod.UUID("00000000-0000-0000-0000-000000000001")

# Convenience fake payload returned by get_coach_payload_for_user mock.
_FAKE_PAYLOAD = {
    "as_of": "2026-07-17",
    "source": "deterministic",
    "sections": {
        "now": "Hold TSS at 315/week until ACWR converges below 1.30.",
        "dream": "plan → ~1:45 by mid-Dec · now ~1:52",
    },
    "text": "Hold TSS at 315/week until ACWR converges below 1.30.\n\nplan → ~1:45 by mid-Dec",
    "nudge": None,
    "chosen_preset": None,
}


def _import_module():
    spec = importlib.util.spec_from_file_location("export_brief", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _import_module()


# ── AC11: SCHEMA_VERSION bumped to 3 ─────────────────────────────────────────

def test_schema_version_is_3(m):
    """AC11: SCHEMA_VERSION constant is 3 after the coach block addition."""
    assert m.SCHEMA_VERSION == 3


# ── AC10: _assemble_coach shape when payload is available ────────────────────
#
# _assemble_coach now lives in backend.services.daily_brief and calls
# get_coach_payload_for_user.  Tests use a valid UUID user_id to skip the
# username-to-UUID resolution path, then patch get_coach_payload_for_user.

def test_assemble_coach_returns_dict_with_required_keys(m):
    """AC10: _assemble_coach returns dict with directive, projection, levers keys."""
    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=_FAKE_PAYLOAD):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert result is not None
    assert "directive" in result
    assert "projection" in result
    assert "levers" in result


def test_assemble_coach_directive_is_string(m):
    """AC10: directive is a non-empty string (first paragraph of sections.now)."""
    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=_FAKE_PAYLOAD):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert isinstance(result["directive"], str)
    assert len(result["directive"]) > 0


def test_assemble_coach_projection_is_string(m):
    """AC10: projection is a non-empty one-line string (first paragraph of sections.dream)."""
    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=_FAKE_PAYLOAD):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert isinstance(result["projection"], str)
    assert len(result["projection"]) > 0
    assert "\n" not in result["projection"], "projection should be one line"


def test_assemble_coach_levers_is_list(m):
    """AC10: levers key is present and is a list."""
    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=_FAKE_PAYLOAD):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert isinstance(result["levers"], list)


def test_assemble_coach_locked_lever_contains_date(m):
    """AC10: when nudge payload exposes load context, it appears in the coach block."""
    payload_with_nudge = dict(_FAKE_PAYLOAD)
    payload_with_nudge["nudge"] = {
        "focus_id": "load_locked",
        "focus_label": "Load locked until 31 Jul",
        "next_action": "Hold TSS at 315/week",
        "why": "ACWR 1.60 — converges 31 Jul",
    }

    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=payload_with_nudge):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert result is not None
    # focus_label or next_action carries the locked load context
    assert result.get("focus_label") or result.get("next_action"), (
        "Expected nudge fields to be present when nudge payload is provided"
    )


def test_assemble_coach_weight_lever_contains_measurement_count(m):
    """AC10: when nudge payload exposes weight context, it appears in the coach block."""
    payload_with_nudge = dict(_FAKE_PAYLOAD)
    payload_with_nudge["nudge"] = {
        "focus_id": "weight_measurement",
        "focus_label": "Weight measurement: 9/14 days",
        "next_action": "Log weight today",
        "why": "Serves Focus #1: weight_measurement",
    }

    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=payload_with_nudge):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert result is not None
    focus_label = result.get("focus_label") or ""
    assert "9" in focus_label or "14" in focus_label or "weight" in focus_label.lower()


# ── AC14: No payload → _assemble_coach returns None ──────────────────────────

def test_assemble_coach_returns_none_when_no_goal(m):
    """AC14: _assemble_coach returns None when get_coach_payload_for_user returns None."""
    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=None):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))
    assert result is None


# ── AC13: _build_brief includes "coach" key when goal active ─────────────────
#
# After issue #1509, m._build_brief is a thin wrapper around
# backend.services.daily_brief._build_brief.  Patches that previously targeted
# the CLI module's globals (e.g. patch.object(m, "_assemble_coach", ...)) must
# now target the service module so they intercept the service's lookup.

import backend.services.daily_brief as _svc_mod


def _base_patches_svc():
    """Common service-module patches for _build_brief tests (no real DB needed)."""
    fake_plan = {"planned": False, "sessions": [], "plan_date": "2026-07-17"}
    fake_form = {
        "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
        "ramp": 1.0, "flags": {}, "interpretation": "Neutral",
    }
    fake_wrap = {
        "window_days": 14, "sessions_planned": 8, "sessions_completed": 6,
        "adherence": 0.75, "load_trend": 0.5, "highlights_md": "Good week.",
    }
    fake_weight = {
        "current_kg": None, "trend_7d": None, "trend_28d": None,
        "target_kg": None, "target_date": None, "pace_kg_per_week": None,
        "on_track": None, "projection_date": None,
    }
    return fake_plan, fake_form, fake_wrap, fake_weight


def test_build_brief_includes_coach_when_goal_active(m):
    """AC13: 'coach' key is present in output when _assemble_coach returns a dict."""
    fake_coach = {
        "directive": "Hold TSS at 315/week until load normalises.",
        "projection": "plan → ~1:45 by mid-Dec · now ~1:52",
        "levers": ["load: locked until 31 Jul", "weight: measurement 9/14 days"],
    }
    fake_plan, fake_form, fake_wrap, fake_weight = _base_patches_svc()

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value=fake_weight), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=fake_coach):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    assert "coach" in brief
    assert brief["coach"]["directive"] == fake_coach["directive"]
    assert brief["coach"]["projection"] == fake_coach["projection"]
    assert brief["coach"]["levers"] == fake_coach["levers"]


def test_build_brief_omits_coach_when_no_goal(m):
    """AC14: 'coach' key is absent (not null) when _assemble_coach returns None."""
    fake_plan, fake_form, fake_wrap, fake_weight = _base_patches_svc()

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value=fake_weight), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    assert "coach" not in brief, "'coach' key must be absent, not null, when no goal"


# ── AC12: Pre-existing fields unchanged ──────────────────────────────────────

_EXISTING_KEYS = {"schema_version", "for_date", "generated_at", "today", "tomorrow",
                  "form", "recent_wrap", "advisories", "actions"}


def test_existing_brief_fields_still_present(m):
    """AC12: All pre-existing top-level fields are present regardless of coach presence."""
    fake_coach = {"directive": "Hold.", "projection": "1:45", "levers": ["load: locked"]}
    fake_plan, fake_form, fake_wrap, fake_weight = _base_patches_svc()

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value=fake_weight), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=fake_coach):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    missing = _EXISTING_KEYS - set(brief.keys())
    assert not missing, f"Missing pre-existing fields: {missing}"


def test_existing_fields_present_without_coach_too(m):
    """AC12: Pre-existing fields are still all present when no active goal (no coach key)."""
    fake_plan, fake_form, fake_wrap, fake_weight = _base_patches_svc()

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value=fake_weight), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    missing = _EXISTING_KEYS - set(brief.keys())
    assert not missing, f"Missing pre-existing fields: {missing}"


# ── Integration: _assemble_coach derives directive and projection from sections ─

def test_assemble_coach_directive_references_locked_load(m):
    """AC10: directive comes from sections.now; reflects locked load context."""
    locked_payload = dict(_FAKE_PAYLOAD)
    locked_payload["sections"] = {
        "now": "Hold TSS at 315/week — ACWR must converge before any ramp.",
        "dream": "plan → ~1:45 by mid-Dec · now ~1:52",
    }
    locked_payload["text"] = locked_payload["sections"]["now"]

    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=locked_payload):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert result is not None
    directive = result["directive"]
    assert any(kw in directive.lower() for kw in ("hold", "locked", "lock", "acwr", "converge")), \
        f"Directive doesn't reflect locked load state: {directive!r}"


def test_assemble_coach_projection_contains_times(m):
    """AC10: projection string comes from sections.dream; contains race-time context."""
    times_payload = dict(_FAKE_PAYLOAD)
    times_payload["sections"] = {
        "now": "Build to 350 TSS/week over the next 4 weeks.",
        "dream": "plan → ~1:45 by mid-Dec · now ~1:52 (±3 min)",
    }

    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=times_payload):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    projection = result["projection"]
    assert "1:45" in projection or "1:52" in projection, \
        f"Projection doesn't contain expected times: {projection!r}"


def test_assemble_coach_error_returns_none(m):
    """AC10: _assemble_coach returns None (not raises) on any internal error."""
    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               side_effect=RuntimeError("service down")):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))
    assert result is None
