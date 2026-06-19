"""Tests for issue #689: Add per-set RPE refinement method for strength TSS

Tests verify that calculate_strength_tss_per_set_with_prefs accepts scale_constant and max_tss
as parameters (never hardcoded), validates them, and produces correct TSS values.
Each test is anchored to a specific acceptance criterion from the issue body.
"""
import pytest
from backend.services.tss import calculate_strength_tss_per_set_with_prefs


# --- Acceptance Criteria Tests ---

def test_strength_tss_per_set__three_set_happy_path():
    """AC: Pure function accepts {reps, rpe} list + scale_constant + max_tss; returns {tss, method, debug}."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert result["method"] == "per_set"
    assert isinstance(result["tss"], int)
    assert 50 <= result["tss"] <= 70


def test_strength_tss_per_set__scale_constant_required():
    """AC: If scale_constant is absent, function returns {tss: null, method: 'none', debug: {reason: '...'}}."""
    sets = [{"reps": 5, "rpe": 8}]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=None, max_tss=150)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert "scale_constant" in result["debug"]["reason"].lower()


def test_strength_tss_per_set__max_tss_required():
    """AC: If max_tss is absent, function returns {tss: null, method: 'none', debug: {reason: '...'}}."""
    sets = [{"reps": 5, "rpe": 8}]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=None)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert "max_tss" in result["debug"]["reason"].lower()


def test_strength_tss_per_set__formula_correctness():
    """AC: Per-set stress = reps × (RPE ÷ 10) × (RPE ÷ 10); sum across sets; scale and clamp."""
    # Set 1 stress: 5 × (8 ÷ 10) × (8 ÷ 10) = 5 × 0.64 = 3.20
    # Set 2 stress: 5 × (9 ÷ 10) × (9 ÷ 10) = 5 × 0.81 = 4.05
    # Set 3 stress: 3 × (10 ÷ 10) × (10 ÷ 10) = 3 × 1.00 = 3.00
    # Raw sum: 10.25
    # Scaled: 10.25 × 5.85 = 59.96
    # Clamped: min(59.96, 150) = 59.96
    # Rounded: 60
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert result["tss"] == 60
    assert result["debug"]["raw_sum"] == pytest.approx(10.25, abs=0.01)
    assert result["debug"]["scaled_sum"] == pytest.approx(59.96, abs=0.01)
    assert result["debug"]["clamped"] == pytest.approx(59.96, abs=0.01)


def test_strength_tss_per_set__tss_whole_number():
    """AC: tss is returned as a whole number (integer) on success, or null on failure."""
    sets = [{"reps": 5, "rpe": 8}]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert isinstance(result["tss"], int)

    result_fail = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=None, max_tss=150)
    assert result_fail["tss"] is None


def test_strength_tss_per_set__method_per_set_success():
    """AC: method returns 'per_set' on success and 'none' on any failure."""
    sets = [{"reps": 5, "rpe": 8}]
    result_success = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert result_success["method"] == "per_set"

    result_fail = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=None, max_tss=150)
    assert result_fail["method"] == "none"


def test_strength_tss_per_set__debug_object_structure():
    """AC: debug object exposes per-set contributions, raw sum, scaled sum, clamped value."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
    ]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert "per_set_contributions" in result["debug"]
    assert "raw_sum" in result["debug"]
    assert "scaled_sum" in result["debug"]
    assert "clamped" in result["debug"]
    assert len(result["debug"]["per_set_contributions"]) == 2


def test_strength_tss_per_set__missing_reps_on_set():
    """AC: If any set missing reps, function returns null with method 'none' and reason string."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"rpe": 9},
    ]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert "reps" in result["debug"]["reason"].lower()


def test_strength_tss_per_set__missing_rpe_on_set():
    """AC: If any set missing RPE, function returns null with method 'none' and reason string."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5},
    ]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert "rpe" in result["debug"]["reason"].lower()


def test_strength_tss_per_set__clamping_behavior():
    """AC: Scaled result is clamped to max_tss named constant, not a literal."""
    # Create a session that would exceed max_tss if unclamped
    sets = [
        {"reps": 100, "rpe": 10},  # Stress: 100 * 1.0 * 1.0 = 100
    ]
    # With scale_constant=5.85, raw_sum=100 → scaled=585, which exceeds max_tss=150
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert result["tss"] == 150  # Should be clamped to max_tss
    assert result["debug"]["scaled_sum"] == pytest.approx(585.0, abs=0.01)
    assert result["debug"]["clamped"] == 150


def test_strength_tss_per_set__tss_range_for_45min_session():
    """AC: Typical hard 45-minute session yields TSS in 50–70 range."""
    # The docstring example (3 sets: 5@RPE8, 5@RPE9, 3@RPE10) yields TSS=60.
    # This test uses that same example to verify it falls in the 50-70 range.
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ]
    result = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=150)
    assert result["tss"] >= 50
    assert result["tss"] <= 70
