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
"""
from __future__ import annotations

import importlib
import importlib.util
import pathlib
from datetime import date
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


# ── AC11: SCHEMA_VERSION bumped to 3 ─────────────────────────────────────────

def test_schema_version_is_3(m):
    """AC11: SCHEMA_VERSION constant is 3 after the coach block addition."""
    assert m.SCHEMA_VERSION == 3


# ── AC10: _assemble_coach shape when goal is active ──────────────────────────

def test_assemble_coach_returns_dict_with_required_keys(m):
    """AC10: _assemble_coach returns dict with directive, projection, levers keys."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300  # 1:45:00
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "locked", "reason": "ACWR 1.60", "unlock_date": date(2026, 7, 31)},
            "weight": {"state": "active", "logged_days": 9, "total_days": 14},
        },
        "timeline": [
            {"start_date": date(2026, 7, 17), "directive": "Hold TSS at 315/week"},
        ],
        "constraints": ["Do not increase load while ACWR > 1.30"],
        "lever_ranking": {"rationale": "CTL gap is primary lever"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    assert result is not None
    assert "directive" in result
    assert "projection" in result
    assert "levers" in result


def test_assemble_coach_directive_is_string(m):
    """AC10: directive is a non-empty string (the Now sentence)."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "locked", "reason": "ACWR elevated", "unlock_date": date(2026, 7, 31)},
            "weight": {"state": "active", "logged_days": 10, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {"rationale": "CTL gap"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    assert isinstance(result["directive"], str)
    assert len(result["directive"]) > 0


def test_assemble_coach_projection_is_string(m):
    """AC10: projection is a non-empty one-line string."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "available"},
            "weight": {"state": "active", "logged_days": 10, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {"rationale": "CTL"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    assert isinstance(result["projection"], str)
    assert len(result["projection"]) > 0
    assert "\n" not in result["projection"], "projection should be one line"


def test_assemble_coach_levers_is_list(m):
    """AC10: levers is a list of compact strings (one per lever)."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "locked", "reason": "ACWR elevated", "unlock_date": date(2026, 7, 31)},
            "weight": {"state": "active", "logged_days": 9, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {"rationale": "CTL"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    assert isinstance(result["levers"], list)
    for item in result["levers"]:
        assert isinstance(item, str)


def test_assemble_coach_locked_lever_contains_date(m):
    """AC10: locked load lever pill contains the unlock date."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "locked", "reason": "ACWR 1.60", "unlock_date": date(2026, 7, 31)},
            "weight": {"state": "active", "logged_days": 9, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {"rationale": "CTL"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    load_lever = next((s for s in result["levers"] if "load" in s.lower()), None)
    assert load_lever is not None, "Expected a 'load' lever string"
    assert "31 Jul" in load_lever or "Jul" in load_lever


def test_assemble_coach_weight_lever_contains_measurement_count(m):
    """AC10: weight lever pill contains logged_days / total_days info."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "available"},
            "weight": {"state": "active", "logged_days": 9, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {"rationale": "CTL"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    weight_lever = next((s for s in result["levers"] if "weight" in s.lower()), None)
    assert weight_lever is not None, "Expected a 'weight' lever string"
    assert "9" in weight_lever or "14" in weight_lever


# ── AC14: No active goal → _assemble_coach returns None ──────────────────────

def test_assemble_coach_returns_none_when_no_goal(m):
    """AC14: _assemble_coach returns None when no active goal exists."""
    with patch.object(m, "_load_goal_for_user", return_value=None):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))
    assert result is None


# ── AC13: _build_brief includes "coach" key when goal active ─────────────────

def _base_patches(m):
    """Return the common patches for _build_brief without a real DB."""
    fake_plan = {"planned": False, "sessions": [], "plan_date": "2026-07-17"}
    fake_form = {
        "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
        "ramp": 1.0, "flags": {}, "interpretation": "Neutral",
    }
    fake_wrap = {
        "window_days": 14, "sessions_planned": 8, "sessions_completed": 6,
        "adherence": 0.75, "load_trend": 0.5, "highlights_md": "Good week.",
    }
    return {
        "_fetch_plan": fake_plan,
        "_assemble_form": fake_form,
        "_assemble_recent_wrap": fake_wrap,
        "_assemble_advisories": [],
    }


def test_build_brief_includes_coach_when_goal_active(m):
    """AC13: 'coach' key is present in output when _assemble_coach returns a dict."""
    fake_coach = {
        "directive": "Hold TSS at 315/week until load normalises.",
        "projection": "plan → ~1:45 by mid-Dec · now ~1:52",
        "levers": ["load: locked until 31 Jul", "weight: measurement 9/14 days"],
    }
    bp = _base_patches(m)

    with patch.object(m, "_fetch_plan", return_value=bp["_fetch_plan"]), \
         patch.object(m, "_assemble_form", return_value=bp["_assemble_form"]), \
         patch.object(m, "_assemble_recent_wrap", return_value=bp["_assemble_recent_wrap"]), \
         patch.object(m, "_assemble_advisories", return_value=bp["_assemble_advisories"]), \
         patch.object(m, "_assemble_coach", return_value=fake_coach):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    assert "coach" in brief
    assert brief["coach"]["directive"] == fake_coach["directive"]
    assert brief["coach"]["projection"] == fake_coach["projection"]
    assert brief["coach"]["levers"] == fake_coach["levers"]


def test_build_brief_omits_coach_when_no_goal(m):
    """AC14: 'coach' key is absent (not null) when _assemble_coach returns None."""
    bp = _base_patches(m)

    with patch.object(m, "_fetch_plan", return_value=bp["_fetch_plan"]), \
         patch.object(m, "_assemble_form", return_value=bp["_assemble_form"]), \
         patch.object(m, "_assemble_recent_wrap", return_value=bp["_assemble_recent_wrap"]), \
         patch.object(m, "_assemble_advisories", return_value=bp["_assemble_advisories"]), \
         patch.object(m, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    assert "coach" not in brief, "'coach' key must be absent, not null, when no goal"


# ── AC12: Pre-existing fields unchanged ──────────────────────────────────────

_EXISTING_KEYS = {"schema_version", "for_date", "generated_at", "today", "tomorrow",
                  "form", "recent_wrap", "advisories", "actions"}


def test_existing_brief_fields_still_present(m):
    """AC12: All pre-existing top-level fields are present regardless of coach presence."""
    bp = _base_patches(m)
    fake_coach = {"directive": "Hold.", "projection": "1:45", "levers": ["load: locked"]}

    with patch.object(m, "_fetch_plan", return_value=bp["_fetch_plan"]), \
         patch.object(m, "_assemble_form", return_value=bp["_assemble_form"]), \
         patch.object(m, "_assemble_recent_wrap", return_value=bp["_assemble_recent_wrap"]), \
         patch.object(m, "_assemble_advisories", return_value=bp["_assemble_advisories"]), \
         patch.object(m, "_assemble_coach", return_value=fake_coach):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    missing = _EXISTING_KEYS - set(brief.keys())
    assert not missing, f"Missing pre-existing fields: {missing}"


def test_existing_fields_present_without_coach_too(m):
    """AC12: Pre-existing fields are still all present when no active goal (no coach key)."""
    bp = _base_patches(m)

    with patch.object(m, "_fetch_plan", return_value=bp["_fetch_plan"]), \
         patch.object(m, "_assemble_form", return_value=bp["_assemble_form"]), \
         patch.object(m, "_assemble_recent_wrap", return_value=bp["_assemble_recent_wrap"]), \
         patch.object(m, "_assemble_advisories", return_value=bp["_assemble_advisories"]), \
         patch.object(m, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 17), "http://localhost:9100", "user-id-1", None)

    missing = _EXISTING_KEYS - set(brief.keys())
    assert not missing, f"Missing pre-existing fields: {missing}"


# ── Integration: _assemble_coach uses plan_state for directive ────────────────

def test_assemble_coach_directive_references_locked_load(m):
    """AC10: directive sentence reflects the 'locked' load lever state."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "locked", "reason": "ACWR 1.60", "unlock_date": date(2026, 7, 31)},
            "weight": {"state": "active", "logged_days": 9, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {"rationale": "CTL"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    # The directive comes from compose_deterministic_message's "Now:" element
    assert result is not None
    directive = result["directive"]
    # Must reference load/ACWR context (locked state references "converges" or similar)
    assert any(kw in directive.lower() for kw in ("hold", "locked", "lock", "acwr", "converge")), \
        f"Directive doesn't reflect locked load state: {directive!r}"


def test_assemble_coach_projection_contains_times(m):
    """AC10: projection string contains the target and current-trend times."""
    mock_goal = MagicMock()
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300   # 1:45:00
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "available"},
            "weight": {"state": "active", "logged_days": 10, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {"rationale": "CTL"},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,    # → 1:45
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,      # → 1:52
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))

    projection = result["projection"]
    assert "1:45" in projection or "1:52" in projection, \
        f"Projection doesn't contain expected times: {projection!r}"


def test_assemble_coach_error_returns_none(m):
    """AC10: _assemble_coach returns None (not raises) on internal error."""
    with patch.object(m, "_load_goal_for_user", side_effect=RuntimeError("DB down")):
        result = m._assemble_coach("user-id-1", date(2026, 7, 17))
    assert result is None
