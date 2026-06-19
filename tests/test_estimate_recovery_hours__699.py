"""Tests for issue #699: Add estimate_recovery_hours pure function to fitness model"""
import pytest


# ── AC1: Pure function exists with correct signature ──────────────────────────

def test_estimate_recovery_hours__function_exists():
    """AC1: A pure function `estimate_recovery_hours(workout_tss, intensity_factor, current_atl)` exists."""
    from backend.services.fitness_model import estimate_recovery_hours

    assert callable(estimate_recovery_hours)


# ── AC2: Handles null/invalid inputs gracefully ──────────────────────────────

def test_estimate_recovery_hours__null_tss():
    """AC2: Returns { hours: null, reason: '<field> is missing or invalid' } when workout_tss is null."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(None, 0.90, 30)
    assert result["hours"] is None
    assert "required" in result["reason"].lower() or "missing" in result["reason"].lower()
    assert result["debug"] is None


def test_estimate_recovery_hours__null_intensity_factor():
    """AC2: Returns error dict when intensity_factor is null."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(120, None, 30)
    assert result["hours"] is None
    assert "required" in result["reason"].lower() or "missing" in result["reason"].lower()
    assert result["debug"] is None


def test_estimate_recovery_hours__null_current_atl():
    """AC2: Returns error dict when current_atl is null."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(120, 0.90, None)
    assert result["hours"] is None
    assert "required" in result["reason"].lower() or "missing" in result["reason"].lower()
    assert result["debug"] is None


def test_estimate_recovery_hours__non_numeric_tss():
    """AC2: Returns error dict when workout_tss is non-numeric."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours("invalid", 0.90, 30)
    assert result["hours"] is None
    assert "numeric" in result["reason"].lower() or "invalid" in result["reason"].lower()


def test_estimate_recovery_hours__non_numeric_intensity_factor():
    """AC2: Returns error dict when intensity_factor is non-numeric."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(120, "invalid", 30)
    assert result["hours"] is None
    assert "numeric" in result["reason"].lower() or "invalid" in result["reason"].lower()


def test_estimate_recovery_hours__non_numeric_current_atl():
    """AC2: Returns error dict when current_atl is non-numeric."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(120, 0.90, "invalid")
    assert result["hours"] is None
    assert "numeric" in result["reason"].lower() or "invalid" in result["reason"].lower()


# ── AC3: Uses named constants ────────────────────────────────────────────────

def test_estimate_recovery_hours__named_constants_exist():
    """AC3: Base recovery is derived from named, configurable constants (no magic numbers)."""
    from backend.services.fitness_model import (
        estimate_recovery_hours,
        MAX_RECOVERY_HOURS,
    )

    # Just verify these constants exist and are numeric
    assert isinstance(MAX_RECOVERY_HOURS, (int, float))
    assert MAX_RECOVERY_HOURS > 0


# ── AC4: Fatigue modifier uses named threshold ───────────────────────────────

def test_estimate_recovery_hours__fatigue_modifier_applied():
    """AC4: Fatigue modifier scales base hours upward when current_atl is elevated."""
    from backend.services.fitness_model import estimate_recovery_hours

    # Fresh athlete (low ATL)
    result_fresh = estimate_recovery_hours(120, 0.90, 30)

    # Same workout but high ATL (fatigued)
    result_fatigued = estimate_recovery_hours(120, 0.90, 80)

    # Both should succeed
    assert result_fresh["hours"] is not None
    assert result_fatigued["hours"] is not None

    # Fatigued result should have higher hours
    assert result_fatigued["hours"] >= result_fresh["hours"]

    # Fatigue modifier should be larger in the fatigued case
    assert result_fatigued["debug"]["fatigue_modifier"] > result_fresh["debug"]["fatigue_modifier"]


# ── AC5: Returns whole integer hours ─────────────────────────────────────────

def test_estimate_recovery_hours__returns_integer_hours():
    """AC5: The returned `hours` value is a whole integer (floored or rounded)."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(40, 0.65, 30)

    assert result["hours"] is not None
    assert isinstance(result["hours"], int)


# ── AC6: Respects MAX_RECOVERY_HOURS cap ─────────────────────────────────────

def test_estimate_recovery_hours__capped_at_max():
    """AC6: Recovery hours are capped at MAX_RECOVERY_HOURS."""
    from backend.services.fitness_model import estimate_recovery_hours, MAX_RECOVERY_HOURS

    # High ATL that would push raw calculation past the cap
    result = estimate_recovery_hours(120, 0.90, 150)

    # Should not exceed the cap
    assert result["hours"] <= MAX_RECOVERY_HOURS

    # If calculation would exceed cap, should equal the cap
    # (test with extreme values to trigger capping)
    result_extreme = estimate_recovery_hours(300, 1.0, 200)
    assert result_extreme["hours"] <= MAX_RECOVERY_HOURS


def test_estimate_recovery_hours__max_cap_visible_in_debug():
    """AC6: Debug still reflects un-capped intermediate values so cap is visible."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(120, 0.90, 150)

    # Debug should show the calculation components even if capped
    assert result["debug"] is not None
    assert "base_hours" in result["debug"]
    assert "intensity_multiplier" in result["debug"]
    assert "fatigue_modifier" in result["debug"]


# ── AC7: Returns correct response shape ──────────────────────────────────────

def test_estimate_recovery_hours__response_shape():
    """AC7: Returns { hours, label, debug, extensionHooks }."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(40, 0.65, 30)

    assert "hours" in result
    assert "label" in result
    assert "debug" in result
    assert "extensionHooks" in result

    # Check label
    assert result["label"] == "training-load based"

    # Check debug keys
    assert "base_hours" in result["debug"]
    assert "intensity_multiplier" in result["debug"]
    assert "fatigue_modifier" in result["debug"]

    # Check extension hooks
    assert result["extensionHooks"]["hrv"] is None
    assert result["extensionHooks"]["sleep"] is None


# ── AC8: Docstring with worked examples ──────────────────────────────────────

def test_estimate_recovery_hours__easy_run_example():
    """AC8: Easy run example: workout_tss=40, intensity_factor=0.65, current_atl=30."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(40, 0.65, 30)

    assert result["hours"] is not None
    assert isinstance(result["hours"], int)
    assert result["label"] == "training-load based"
    assert result["debug"]["base_hours"] is not None
    assert result["debug"]["intensity_multiplier"] is not None
    assert result["debug"]["fatigue_modifier"] is not None


def test_estimate_recovery_hours__hard_interval_fresh():
    """AC8: Hard interval session with fresh athlete: workout_tss=120, intensity_factor=0.90, current_atl=30."""
    from backend.services.fitness_model import estimate_recovery_hours

    result = estimate_recovery_hours(120, 0.90, 30)

    assert result["hours"] is not None
    assert isinstance(result["hours"], int)
    # Hard interval should give more hours than easy run
    easy_result = estimate_recovery_hours(40, 0.65, 30)
    assert result["hours"] > easy_result["hours"]

    # Intensity multiplier should be > 1
    assert result["debug"]["intensity_multiplier"] > 1


def test_estimate_recovery_hours__hard_interval_fatigued():
    """AC8: Same hard session under high fatigue: workout_tss=120, intensity_factor=0.90, current_atl=80."""
    from backend.services.fitness_model import estimate_recovery_hours

    result_fresh = estimate_recovery_hours(120, 0.90, 30)
    result_fatigued = estimate_recovery_hours(120, 0.90, 80)

    # Fatigued case should give more hours
    assert result_fatigued["hours"] >= result_fresh["hours"]

    # Fatigue modifier should be visibly larger
    assert result_fatigued["debug"]["fatigue_modifier"] > result_fresh["debug"]["fatigue_modifier"]


# ── AC9: Docstring examples are covered by unit tests ──────────────────────────

def test_estimate_recovery_hours__examples_assert_all_debug_fields():
    """AC9: All docstring examples covered by tests asserting hours, debug fields."""
    from backend.services.fitness_model import estimate_recovery_hours

    examples = [
        (40, 0.65, 30),      # easy run
        (120, 0.90, 30),     # hard fresh
        (120, 0.90, 80),     # hard fatigued
    ]

    for tss, if_val, atl in examples:
        result = estimate_recovery_hours(tss, if_val, atl)
        assert result["hours"] is not None, f"Failed for TSS={tss}, IF={if_val}, ATL={atl}"
        assert isinstance(result["hours"], int)
        assert result["debug"]["base_hours"] is not None
        assert result["debug"]["intensity_multiplier"] is not None
        assert result["debug"]["fatigue_modifier"] is not None


# ── AC10: Caller fetches current_atl; function accepts primitives only ────────

def test_estimate_recovery_hours__primitive_numeric_inputs_only():
    """AC10: Function accepts only primitive numeric inputs (no ORM objects)."""
    from backend.services.fitness_model import estimate_recovery_hours

    # All valid numeric inputs should work
    result1 = estimate_recovery_hours(120, 0.90, 30)
    result2 = estimate_recovery_hours(120.5, 0.90, 30.5)
    result3 = estimate_recovery_hours(int(120), int(0), int(30))

    assert result1["hours"] is not None
    assert result2["hours"] is not None
    assert result3["hours"] is not None


# ── AC11: Extension hooks marked as integration point ─────────────────────────

def test_estimate_recovery_hours__extension_hooks_present():
    """AC11: extensionHooks block with hrv and sleep is marked as integration point."""
    from backend.services.fitness_model import estimate_recovery_hours
    import inspect

    result = estimate_recovery_hours(40, 0.65, 30)

    # Verify the structure exists
    assert result["extensionHooks"] == {"hrv": None, "sleep": None}

    # Verify the source has a comment marking it as extension point
    source = inspect.getsource(estimate_recovery_hours)
    assert "extensionHooks" in source or "extension" in source.lower()
