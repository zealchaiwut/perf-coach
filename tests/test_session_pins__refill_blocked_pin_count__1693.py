"""Issue #1693: fill_slot must refuse loudly when pinned-row count exceeds 12.

Previously, >12 pinned rows caused validate_slot to fail, the pointless RNG-seed
retry also failed, then fill_slot silently replaced ALL content with a template.
The athlete received a 200 OK whose exercises bore no relation to their pins.

Fix: an early guard in fill_slot detects len(pre_placed) > 12 BEFORE calling
fill_strength and returns refill_blocked=True with a clear reason, preserving the
original exercises.
"""
from __future__ import annotations

import copy

from backend.services.plan_pattern_fill import fill_slot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pinned_row(name: str, idx: int = 0) -> dict:
    return {
        "name": name,
        "sets": 3,
        "reps": "10",
        "load": "moderate",
        "block": "Accessories",
        "source": "swap",
        "pinned": True,
        "spend_tss": 3,
        "spend_min": 5,
    }


def _make_pinned_exercises(n: int) -> list[dict]:
    return [_pinned_row(f"Exercise {i + 1}", i) for i in range(n)]


def _strength_slot(target_tss: float = 40, duration_minutes: int = 60) -> dict:
    return {
        "workout_type": "strength",
        "subtype": "strength_lower",
        "target_tss": target_tss,
        "duration_minutes": duration_minutes,
        "day_offset": 1,
    }


# ---------------------------------------------------------------------------
# AC1: >12 pinned rows → refill_blocked=True, not a template swap
# ---------------------------------------------------------------------------

def test_refill_blocked_when_13_pinned_rows():
    """13 pinned rows must return refill_blocked, not a template result."""
    exercises = _make_pinned_exercises(13)
    current = {"exercises": copy.deepcopy(exercises), "source": "user", "intent": "Lower body strength"}
    slot = _strength_slot()

    out = fill_slot(slot, current=current, respect_exercise_pins=True)

    assert out.get("refill_blocked") is True, (
        f"Expected refill_blocked=True, got {out.get('refill_blocked')!r}. "
        f"Exercises returned: {[e.get('name') for e in (out.get('exercises') or [])]}"
    )


# ---------------------------------------------------------------------------
# AC2: refill_reason mentions the count (readable error)
# ---------------------------------------------------------------------------

def test_refill_blocked_reason_mentions_count():
    """The refill_reason must tell the athlete how many pins they have vs the max."""
    exercises = _make_pinned_exercises(13)
    current = {"exercises": copy.deepcopy(exercises), "source": "user"}
    slot = _strength_slot()

    out = fill_slot(slot, current=current, respect_exercise_pins=True)

    reason = out.get("refill_reason") or ""
    # Must mention the number 13 or 12 (or both) so a user can act on it.
    assert "13" in reason or "12" in reason, (
        f"refill_reason should mention the relevant counts, got: {reason!r}"
    )


# ---------------------------------------------------------------------------
# AC3: original exercises are preserved in the blocked response
# ---------------------------------------------------------------------------

def test_refill_blocked_preserves_original_exercises():
    """Blocked response must return the original exercises, not template content."""
    exercises = _make_pinned_exercises(13)
    original_names = [e["name"] for e in exercises]
    current = {"exercises": copy.deepcopy(exercises), "source": "user"}
    slot = _strength_slot()

    out = fill_slot(slot, current=current, respect_exercise_pins=True)

    assert out.get("refill_blocked") is True
    returned_names = [e.get("name") for e in (out.get("exercises") or [])]
    assert returned_names == original_names, (
        f"Expected original exercises preserved. Got: {returned_names}"
    )


# ---------------------------------------------------------------------------
# AC4: exactly 12 pinned rows must NOT trigger the count guard
# ---------------------------------------------------------------------------

def test_refill_not_blocked_by_count_at_exactly_12_pinned():
    """12 pinned rows is at the limit — count guard must not fire."""
    exercises = _make_pinned_exercises(12)
    current = {"exercises": copy.deepcopy(exercises), "source": "user"}
    # Use a high budget so TSS contract passes too.
    slot = _strength_slot(target_tss=200, duration_minutes=120)

    out = fill_slot(slot, current=current, respect_exercise_pins=True)

    # Should NOT be blocked by the count guard (may be blocked by something else,
    # but not by pinned count alone).
    reason = out.get("refill_reason") or ""
    assert not ("13" in reason and "12" in reason) or out.get("refill_blocked") is not True or \
        "exceed" not in reason.lower(), (
        "12 pinned rows should not trigger the >12 count guard"
    )
    # More direct: the "pinned_count_exceeds_max" step must not appear in fill_log.
    fill_log = out.get("fill_log") or {}
    steps = fill_log.get("steps") or []
    ops = [s.get("op") for s in steps]
    assert "pinned_count_exceeds_max" not in ops, (
        f"Count guard should not fire for exactly 12 pinned rows. Steps: {ops}"
    )


# ---------------------------------------------------------------------------
# AC5: fill_slot without respect_exercise_pins is unaffected (no regression)
# ---------------------------------------------------------------------------

def test_no_regression_without_pin_respect():
    """When respect_exercise_pins=False, the >12 guard must not apply."""
    exercises = _make_pinned_exercises(13)
    current = {"exercises": copy.deepcopy(exercises), "source": "user"}
    slot = _strength_slot()

    # Default: respect_exercise_pins=False → keep-user path applies
    out = fill_slot(slot, current=current, respect_exercise_pins=False)

    # With source="user" and no pin respect, the slot is kept as-is (not blocked).
    assert out.get("refill_blocked") is not True


# ---------------------------------------------------------------------------
# AC6: plyo slot with >12 pinned rows is also blocked
# ---------------------------------------------------------------------------

def test_refill_blocked_for_plyo_slot_with_13_pinned():
    """The guard applies to plyo slots, not just strength."""
    exercises = _make_pinned_exercises(13)
    current = {"exercises": copy.deepcopy(exercises), "source": "user"}
    slot = {
        "workout_type": "plyo",
        "subtype": "plyo",
        "target_tss": 40,
        "duration_minutes": 60,
        "day_offset": 2,
    }

    out = fill_slot(slot, current=current, respect_exercise_pins=True)

    assert out.get("refill_blocked") is True
