"""Sprint 136 — mobility sessions + worker rebuild (WC-09..WC-13)."""
from __future__ import annotations

from datetime import date

import pytest

from backend.services.plan_extras import apply_prefs_extras
from backend.services.plan_mobility import attach_mobility_slots, mobility_subtype_for_day
from backend.services.plan_pattern_seeds import default_mobility_patterns
from backend.services.plan_draft import _session_to_planned_body, _VALID_SESSION_TYPES
from backend.services.training_load import estimate_planned_session_metrics


def _week():
    return [
        {"day_offset": 0, "workout_type": "strength", "subtype": "strength", "target_tss": 30},
        {"day_offset": 1, "workout_type": "run", "subtype": "easy_run", "target_tss": 40},
        {"day_offset": 2, "workout_type": "rest", "subtype": "rest", "target_tss": 0},
        {"day_offset": 3, "workout_type": "run", "subtype": "tempo", "target_tss": 65},
        {"day_offset": 4, "workout_type": "rest", "subtype": "rest", "target_tss": 0},
        {"day_offset": 5, "workout_type": "run", "subtype": "long_run", "target_tss": 95},
        {"day_offset": 6, "workout_type": "rest", "subtype": "rest", "target_tss": 0},
    ]


def test_mobility_in_valid_session_types():
    assert "mobility" in _VALID_SESSION_TYPES


def test_mobility_session_body_has_optional_structure():
    ws = date(2026, 9, 28)
    body = _session_to_planned_body(ws, {
        "day_offset": 0,
        "workout_type": "mobility",
        "intent": "Hip stretch",
        "exercises": [{"name": "Pigeon", "sets": 1, "reps": "45s hold"}],
        "duration_minutes": 12,
    })
    assert body is not None
    assert body["session_type"] == "mobility"
    assert body["structure"]["optional"] is True
    assert body["structure"]["exercises"]


def test_mobility_estimated_tss_is_zero():
    est = estimate_planned_session_metrics({}, "mobility", {"exercises": []})
    assert est["estimated_tss"] == 0


def test_apply_prefs_extras_adds_mobility_slots_not_daily_extras():
    sk = {"week_start": "2026-09-28", "budget": {}, "slots": _week()}
    out = apply_prefs_extras(sk, prefs={"stretch_daily_min": 12}, week_start=date(2026, 9, 28))
    mobility = [s for s in out["slots"] if s.get("workout_type") == "mobility"]
    assert len(mobility) == 7
    assert all(s["target_tss"] == 0 for s in mobility)
    assert not any(s.get("daily_extras") for s in out["slots"] if not s.get("is_mobility"))


def test_mobility_subtype_rules():
    slots = _week()
    assert mobility_subtype_for_day(slots[0], slots, 0) == "stretch_core"
    assert mobility_subtype_for_day(slots[1], slots, 1) == "stretch_hips"
    assert mobility_subtype_for_day(slots[3], slots, 3) == "stretch_posterior"
    assert mobility_subtype_for_day(slots[5], slots, 5) == "stretch_light"


def test_default_mobility_patterns_seeded():
    pats = default_mobility_patterns()
    subs = {p["subtype"] for p in pats}
    assert subs == {
        "stretch_core", "stretch_hips", "stretch_posterior",
        "stretch_upper", "yin", "stretch_light",
    }
    assert all(p["kind"] == "mobility" for p in pats)


def test_plan_matching_excludes_mobility_and_skipped():
    src = open("backend/services/plan_matching.py", encoding="utf-8").read()
    assert 'PlannedSession.session_type != "mobility"' in src
    assert 'PlannedSession.status != "skipped"' in src


def test_worker_dispatches_plan_draft():
    import backend.worker_app as w

    assert "plan_draft" in w._DISPATCH
