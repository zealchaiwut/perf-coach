"""Tests for issue #689: Add per-set RPE refinement method for strength TSS.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria covered:
  AC-1  — pure function accepts list of {reps, rpe} objects plus scale_constant and
           max_tss (from user_preferences); returns {tss, method, debug}
  AC-2  — scale_constant and max_tss are never hardcoded; absent → null result
  AC-3  — per-set stress = reps × (rpe/10) × (rpe/10)
  AC-4  — raw session stress = sum of set stresses × scale_constant
  AC-5  — scaled result clamped to max_tss (named constant, not a literal)
  AC-6  — tss returned as whole number (int) on success, null on failure
  AC-7  — method is "per_set" on success, "none" on any failure
  AC-8  — debug exposes: per_set_contributions, raw_sum, scaled_sum, clamped
  AC-9  — missing reps or rpe → null with method:"none" and reason identifying
           the missing field and set index
  AC-10 — docstring includes three-set worked example
  AC-11 — all database access lives in the caller; function is pure (no I/O)
  AC-12 — unit tests: 3-set happy path, missing RPE, missing reps, missing
           scale_constant, missing max_tss, clamping behavior
"""
import inspect

import pytest

from backend.services.tss import calculate_strength_tss_per_set_with_prefs


# ── AC-12 / AC-1 / AC-3 / AC-4 / AC-8: three-set happy path ─────────────────

def test_three_set_happy_path():
    """AC-12: three-set happy path yields tss between 50 and 70."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    assert result["method"] == "per_set"
    assert isinstance(result["tss"], int)
    assert 50 <= result["tss"] <= 70


def test_three_set_arithmetic():
    """AC-3 / AC-4 / AC-8: verify per-set formula and scaling match worked example."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    debug = result["debug"]

    # Set stresses: 5*(0.8^2)=3.2, 5*(0.9^2)=4.05, 3*(1.0^2)=3.0
    assert debug["per_set_contributions"] == pytest.approx([3.2, 4.05, 3.0])
    assert debug["raw_sum"] == pytest.approx(10.25)
    assert debug["scaled_sum"] == pytest.approx(10.25 * 5.85)
    assert debug["clamped"] == pytest.approx(min(debug["scaled_sum"], 150))
    assert result["tss"] == round(debug["clamped"])


def test_debug_keys_present_on_success():
    """AC-8: debug dict exposes all four required fields on success."""
    result = calculate_strength_tss_per_set_with_prefs(
        [{"reps": 5, "rpe": 8}], scale_constant=5.85, max_tss=150
    )
    debug = result["debug"]
    assert "per_set_contributions" in debug
    assert "raw_sum" in debug
    assert "scaled_sum" in debug
    assert "clamped" in debug


def test_return_shape_success():
    """AC-1: success result has exactly tss, method, debug keys."""
    result = calculate_strength_tss_per_set_with_prefs(
        [{"reps": 5, "rpe": 8}], scale_constant=5.85, max_tss=150
    )
    assert set(result.keys()) == {"tss", "method", "debug"}


def test_return_shape_failure():
    """AC-1: failure result also has exactly tss, method, debug keys."""
    result = calculate_strength_tss_per_set_with_prefs(
        [], scale_constant=5.85, max_tss=150
    )
    assert set(result.keys()) == {"tss", "method", "debug"}


# ── AC-12 / AC-9: missing RPE on one set ─────────────────────────────────────

def test_missing_rpe_returns_null():
    """AC-12 / AC-9: missing rpe on one set → null, method:'none', reason with set index."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": None},
    ]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    reason = result["debug"]["reason"]
    assert reason  # non-empty
    # reason should identify the missing field and index
    assert "rpe" in reason.lower()
    assert "1" in reason  # set index 1


def test_missing_rpe_key_returns_null():
    """AC-9: set dict missing 'rpe' key → null result, never raises."""
    sets = [{"reps": 5}]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


# ── AC-12 / AC-9: missing reps on one set ────────────────────────────────────

def test_missing_reps_returns_null():
    """AC-12 / AC-9: missing reps on one set → null, method:'none', reason with set index."""
    sets = [
        {"reps": None, "rpe": 8},
        {"reps": 5, "rpe": 9},
    ]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    reason = result["debug"]["reason"]
    assert "reps" in reason.lower()
    assert "0" in reason  # set index 0


def test_missing_reps_key_returns_null():
    """AC-9: set dict missing 'reps' key → null result, never raises."""
    sets = [{"rpe": 8}]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


# ── AC-12 / AC-2: missing scale_constant preference ──────────────────────────

def test_missing_scale_constant_returns_null():
    """AC-12 / AC-2: scale_constant=None → null, method:'none', reason in debug."""
    sets = [{"reps": 5, "rpe": 8}]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=None, max_tss=150
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


def test_missing_scale_constant_reason_mentions_preference():
    """AC-2: reason string explains scale_constant is absent from preferences."""
    result = calculate_strength_tss_per_set_with_prefs(
        [{"reps": 5, "rpe": 8}], scale_constant=None, max_tss=150
    )
    reason = result["debug"]["reason"].lower()
    assert "scale" in reason or "scale_constant" in reason


# ── AC-12 / AC-2: missing max_tss preference ─────────────────────────────────

def test_missing_max_tss_returns_null():
    """AC-12 / AC-2: max_tss=None → null, method:'none', reason in debug."""
    sets = [{"reps": 5, "rpe": 8}]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=None
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


def test_missing_max_tss_reason_mentions_preference():
    """AC-2: reason string explains max_tss is absent from preferences."""
    result = calculate_strength_tss_per_set_with_prefs(
        [{"reps": 5, "rpe": 8}], scale_constant=5.85, max_tss=None
    )
    reason = result["debug"]["reason"].lower()
    assert "max" in reason or "max_tss" in reason


# ── AC-12 / AC-5: clamping when scaled value exceeds max_tss ─────────────────

def test_clamping_when_scaled_exceeds_max():
    """AC-12 / AC-5: when scaled_sum > max_tss, result is clamped to max_tss."""
    # 1000 reps at RPE 10 will far exceed any reasonable max_tss
    sets = [{"reps": 1000, "rpe": 10}]
    max_tss = 150
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=max_tss
    )
    assert result["tss"] == max_tss
    assert result["debug"]["clamped"] == pytest.approx(max_tss)
    assert result["debug"]["scaled_sum"] > max_tss


def test_not_clamped_when_below_max():
    """AC-5: result below max_tss is returned as-is, not reduced."""
    sets = [{"reps": 1, "rpe": 1}]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    assert result["tss"] is not None
    assert result["tss"] < 150


# ── AC-6: tss type ────────────────────────────────────────────────────────────

def test_tss_is_integer_on_success():
    """AC-6: tss is a whole number (int) on success."""
    result = calculate_strength_tss_per_set_with_prefs(
        [{"reps": 5, "rpe": 8}], scale_constant=5.85, max_tss=150
    )
    assert isinstance(result["tss"], int)


def test_tss_is_null_on_failure():
    """AC-6: tss is null when any required input is absent."""
    result = calculate_strength_tss_per_set_with_prefs(
        [{"reps": 5, "rpe": None}], scale_constant=5.85, max_tss=150
    )
    assert result["tss"] is None


# ── AC-7: method values ───────────────────────────────────────────────────────

def test_method_per_set_on_success():
    """AC-7: method is 'per_set' when computation succeeds."""
    result = calculate_strength_tss_per_set_with_prefs(
        [{"reps": 5, "rpe": 8}], scale_constant=5.85, max_tss=150
    )
    assert result["method"] == "per_set"


def test_method_none_on_failure():
    """AC-7: method is 'none' on any failure."""
    for args in [
        ([], 5.85, 150),           # empty set list
        ([{"reps": 5, "rpe": None}], 5.85, 150),  # missing rpe
        ([{"reps": None, "rpe": 8}], 5.85, 150),  # missing reps
        ([{"reps": 5, "rpe": 8}], None, 150),     # missing scale_constant
        ([{"reps": 5, "rpe": 8}], 5.85, None),    # missing max_tss
    ]:
        result = calculate_strength_tss_per_set_with_prefs(*args)
        assert result["method"] == "none", f"Expected 'none' for args={args}"


# ── AC-2: constants not hardcoded (no module-level constant referenced) ───────

def test_scale_constant_and_max_tss_not_hardcoded():
    """AC-2: different scale_constant values produce proportionally different results."""
    sets = [{"reps": 5, "rpe": 8}]
    r1 = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.0, max_tss=500)
    r2 = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=10.0, max_tss=500)
    # With double the scale_constant, scaled_sum should be double
    assert r2["debug"]["scaled_sum"] == pytest.approx(r1["debug"]["scaled_sum"] * 2)


def test_max_tss_caps_result():
    """AC-2 / AC-5: different max_tss values are respected, not a hardcoded constant."""
    sets = [{"reps": 100, "rpe": 10}]
    r_low = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=50)
    r_high = calculate_strength_tss_per_set_with_prefs(sets, scale_constant=5.85, max_tss=200)
    assert r_low["tss"] == 50
    assert r_high["tss"] == 200


# ── AC-11 / pure function check ───────────────────────────────────────────────

def test_function_is_pure_no_db_access():
    """AC-11: function source contains no DB-related identifiers."""
    src = inspect.getsource(calculate_strength_tss_per_set_with_prefs)
    for forbidden in ("db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in src, f"DB access found: {forbidden!r}"


# ── AC-10: docstring worked example ──────────────────────────────────────────

def test_docstring_includes_three_set_worked_example():
    """AC-10: docstring contains a three-set worked example with intermediate values."""
    doc = calculate_strength_tss_per_set_with_prefs.__doc__ or ""
    # Must contain reps/rpe reference
    assert "rpe" in doc.lower() or "RPE" in doc
    assert "reps" in doc.lower() or "Reps" in doc
    # Must show at least one intermediate value from the worked example
    assert "3.2" in doc or "3.20" in doc or "10.25" in doc


# ── AC-9: reason identifies missing field and set index ──────────────────────

def test_reason_identifies_set_index_for_missing_rpe():
    """AC-9: reason string identifies both 'rpe' and the set index."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 3, "rpe": 9},
        {"reps": 4, "rpe": None},  # index 2 is missing rpe
    ]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    reason = result["debug"]["reason"]
    assert "rpe" in reason.lower()
    assert "2" in reason


def test_reason_identifies_set_index_for_missing_reps():
    """AC-9: reason string identifies both 'reps' and the set index."""
    sets = [
        {"reps": None, "rpe": 8},  # index 0 is missing reps
        {"reps": 5, "rpe": 9},
    ]
    result = calculate_strength_tss_per_set_with_prefs(
        sets, scale_constant=5.85, max_tss=150
    )
    reason = result["debug"]["reason"]
    assert "reps" in reason.lower()
    assert "0" in reason
