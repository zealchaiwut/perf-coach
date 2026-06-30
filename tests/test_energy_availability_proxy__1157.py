"""Unit tests for compute_ea_proxy (issue #1157).

AC coverage:
- AC1: EA proxy is computed from intake relative to training load
- AC2: Proxy exposed as named field in return value
- AC3: low_ea=True when proxy indicates insufficient energy
- AC4: low_ea=False when intake is sufficient
- AC5: LOW_EA_THRESHOLD named constant (not magic number)
- AC6: py_compile (checked via separate UAT step)
- AC7: No calorie prescription — output is sufficiency signal only

UAT step map:
- UAT1: low intake + high load → proxy computed, low_ea=True
- UAT2: adequate intake + moderate load → low_ea=False
- UAT3: zero training_load + non-zero intake → no error, proxy and flag returned
- UAT4: zero intake + non-zero load → maximal insufficiency, low_ea=True
"""
import pytest

from backend.services.ea_proxy import LOW_EA_THRESHOLD, compute_ea_proxy


# ── UAT Step 1 ────────────────────────────────────────────────────────────────

def test_low_intake_high_load_raises_flag():
    """UAT1: low intake vs high load → proxy computed, low_ea=True (AC1, AC2, AC3)."""
    result = compute_ea_proxy(intake=20.0, training_load=200.0)
    assert "ea_proxy" in result, "ea_proxy must be a named field in the result"
    assert "low_ea" in result, "low_ea must be a named field in the result"
    assert result["ea_proxy"] is not None
    assert result["low_ea"] is True


# ── UAT Step 2 ────────────────────────────────────────────────────────────────

def test_adequate_intake_moderate_load_no_flag():
    """UAT2: adequate intake vs moderate load → low_ea=False (AC1, AC2, AC4)."""
    result = compute_ea_proxy(intake=200.0, training_load=100.0)
    assert "ea_proxy" in result
    assert "low_ea" in result
    assert result["ea_proxy"] is not None
    assert result["low_ea"] is False


# ── UAT Step 3 ────────────────────────────────────────────────────────────────

def test_zero_load_nonzero_intake_no_error():
    """UAT3: zero training_load + non-zero intake → no error, proxy and flag returned (AC1, AC2)."""
    result = compute_ea_proxy(intake=150.0, training_load=0.0)
    assert "ea_proxy" in result
    assert "low_ea" in result
    # No load demand means no insufficiency
    assert result["low_ea"] is False


def test_zero_load_zero_intake_no_error():
    """Both zero → no error; proxy and flag are returned."""
    result = compute_ea_proxy(intake=0.0, training_load=0.0)
    assert "ea_proxy" in result
    assert "low_ea" in result


# ── UAT Step 4 ────────────────────────────────────────────────────────────────

def test_zero_intake_nonzero_load_maximal_insufficiency():
    """UAT4: zero intake + non-zero load → maximal insufficiency, low_ea=True (AC3)."""
    result = compute_ea_proxy(intake=0.0, training_load=100.0)
    assert "ea_proxy" in result
    assert "low_ea" in result
    assert result["low_ea"] is True
    assert result["ea_proxy"] == pytest.approx(0.0)


# ── AC5: named threshold constant ─────────────────────────────────────────────

def test_threshold_is_named_constant():
    """AC5: LOW_EA_THRESHOLD is importable, numeric, and positive."""
    assert isinstance(LOW_EA_THRESHOLD, (int, float))
    assert LOW_EA_THRESHOLD > 0


def test_flag_false_at_exact_threshold():
    """Proxy exactly at threshold → not flagged (boundary is inclusive-sufficient)."""
    # intake / load = LOW_EA_THRESHOLD exactly → sufficient
    result = compute_ea_proxy(intake=LOW_EA_THRESHOLD * 100.0, training_load=100.0)
    assert result["low_ea"] is False


def test_flag_true_just_below_threshold():
    """Proxy just below threshold → low_ea=True (strict boundary check)."""
    epsilon = 0.001
    result = compute_ea_proxy(
        intake=(LOW_EA_THRESHOLD - epsilon) * 100.0,
        training_load=100.0,
    )
    assert result["low_ea"] is True


# ── AC1: proxy formula ────────────────────────────────────────────────────────

def test_proxy_value_is_intake_to_load_ratio():
    """AC1: EA proxy equals intake / training_load when load > 0."""
    intake, load = 150.0, 100.0
    result = compute_ea_proxy(intake=intake, training_load=load)
    assert result["ea_proxy"] == pytest.approx(intake / load)


# ── AC7: no calorie prescription ─────────────────────────────────────────────

def test_no_absolute_calorie_output():
    """AC7: return value must not contain calorie prescriptions or absolute targets."""
    result = compute_ea_proxy(intake=150.0, training_load=100.0)
    forbidden = {"calories", "target", "recommendation", "prescription", "daily_target"}
    assert forbidden.isdisjoint(result.keys()), (
        f"Return value must not contain prescription keys; found {forbidden & result.keys()}"
    )
