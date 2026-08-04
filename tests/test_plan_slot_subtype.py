"""Subtype binding for plan_slot fill (UI intervals ≠ easy template)."""
from __future__ import annotations

from backend.services.plan_slot import (
    normalize_slot_subtype,
    template_content_for_slot,
    validate_slot,
)


def test_normalize_ui_intervals():
    assert normalize_slot_subtype("run", "intervals") == "intervals"
    assert normalize_slot_subtype("run", "easy") == "easy_run"
    assert normalize_slot_subtype("run", "long") == "long_run"
    assert normalize_slot_subtype("run", None) == "easy_run"


def test_coerce_ui_subtype_accepts_skeleton_aliases():
    from backend.services.plan_suggestions import coerce_ui_subtype
    assert coerce_ui_subtype("run", "easy_run") == "easy"
    assert coerce_ui_subtype("run", "easy") == "easy"
    assert coerce_ui_subtype("run", "long_run") == "long"
    assert coerce_ui_subtype("strength", "strength_upper") == "upper"
    assert coerce_ui_subtype("run", "bogus") is None


def test_intervals_template_is_not_easy():
    slot = {
        "day_offset": 2,
        "workout_type": "run",
        "target_tss": 44,
        "duration_minutes": 70,
        "subtype": "intervals",
    }
    content = template_content_for_slot(slot)
    assert "easy aerobic" not in (content["intent"] or "").lower()
    assert validate_slot(content, slot) == []
    main = next(b for b in content["blocks"] if b.get("phase") == "main")
    assert int(main.get("repeat") or 0) >= 2


def test_validate_rejects_easy_content_for_intervals():
    slot = {
        "day_offset": 2,
        "workout_type": "run",
        "target_tss": 44,
        "duration_minutes": 70,
        "subtype": "intervals",
    }
    easy = {
        "intent": "Easy aerobic run",
        "blocks": [
            {"phase": "warmup", "duration_min": 10, "target": "easy"},
            {"phase": "main", "duration_min": 50, "target": "easy, conversational"},
            {"phase": "cooldown", "duration_min": 10, "target": "easy"},
        ],
    }
    errs = validate_slot(easy, slot)
    assert any("intervals" in e for e in errs)


def test_plyo_template_is_short_not_lower_strength():
    slot = {
        "day_offset": 1,
        "workout_type": "plyo",
        "target_tss": 20,
        "duration_minutes": 20,
        "subtype": "plyo",
    }
    content = template_content_for_slot(slot)
    assert "plyometric" in (content["intent"] or "").lower()
    assert "Lower body" not in (content["intent"] or "")
    blocks = {e.get("block") for e in content["exercises"]}
    assert "Heavy compound" not in blocks
    assert "Plyometrics" in blocks
    assert validate_slot(content, slot) == []
