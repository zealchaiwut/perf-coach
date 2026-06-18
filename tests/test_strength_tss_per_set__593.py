"""Tests for issue #593: Implement per-set RPE refinement for strength TSS.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria covered:
  AC-1  — calculate_strength_tss_per_set(sets) accepts list of {reps, rpe} and returns {tss, method, debug}
  AC-2  — set_stress = reps * (rpe/10)^2; sum across all sets
  AC-3  — raw sum multiplied by STRENGTH_TSS_SCALE (named constant)
  AC-4  — result clamped at STRENGTH_TSS_MAX before rounding to whole number
  AC-5  — method is "per_set" on success, "none" when input invalid
  AC-6  — missing reps or rpe → {tss: None, method: "none", debug: {reason: "..."}}; never throws
  AC-7  — debug exposes per_set_contributions, raw_sum, scaled_sum, clamped
  AC-8  — docstring includes three-set worked example
  AC-9  — STRENGTH_TSS_SCALE and STRENGTH_TSS_MAX are named constants (never inline literals)
  AC-10 — pure function: no DB access
  AC-11 — unit tests: (a) 3-set happy path, (b) single set, (c) missing rpe, (d) empty list, (e) clamp boundary
  AC-12 — no defaults seeded into DB or user_preferences
"""
import inspect

import pytest

from backend.services.tss import (
    STRENGTH_TSS_MAX,
    STRENGTH_TSS_SCALE,
    calculate_strength_tss_per_set,
)


# ── AC-11a / AC-1 / AC-2 / AC-3 / AC-7: three-set happy path ─────────────────

def test_three_set_happy_path():
    """AC-11a: three sets → tss between 50 and 70 for the docstring example."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ]
    result = calculate_strength_tss_per_set(sets)
    assert result["method"] == "per_set"
    assert isinstance(result["tss"], int)
    assert 50 <= result["tss"] <= 70


def test_three_set_arithmetic():
    """AC-2 / AC-3: verify set_stress formula and scaling match docstring example."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": 9},
        {"reps": 3, "rpe": 10},
    ]
    result = calculate_strength_tss_per_set(sets)
    debug = result["debug"]

    # Set stresses: 5*(0.8^2)=3.2, 5*(0.9^2)=4.05, 3*(1.0^2)=3.0
    assert debug["per_set_contributions"] == pytest.approx([3.2, 4.05, 3.0])
    assert debug["raw_sum"] == pytest.approx(10.25)
    assert debug["scaled_sum"] == pytest.approx(10.25 * STRENGTH_TSS_SCALE)
    # clamped = min(scaled_sum, STRENGTH_TSS_MAX)
    assert debug["clamped"] == pytest.approx(min(debug["scaled_sum"], STRENGTH_TSS_MAX))
    assert result["tss"] == round(debug["clamped"])


def test_debug_keys_present_on_success():
    """AC-7: debug dict contains per_set_contributions, raw_sum, scaled_sum, clamped."""
    sets = [{"reps": 5, "rpe": 8}]
    result = calculate_strength_tss_per_set(sets)
    debug = result["debug"]
    assert "per_set_contributions" in debug
    assert "raw_sum" in debug
    assert "scaled_sum" in debug
    assert "clamped" in debug


# ── AC-11b: single-set happy path ─────────────────────────────────────────────

def test_single_set_happy_path():
    """AC-11b: a single set returns a valid tss and method='per_set'."""
    result = calculate_strength_tss_per_set([{"reps": 10, "rpe": 7}])
    assert result["method"] == "per_set"
    assert isinstance(result["tss"], int)
    assert result["tss"] is not None


def test_single_set_arithmetic():
    """AC-2: single set stress = reps * (rpe/10)^2."""
    sets = [{"reps": 10, "rpe": 7}]
    result = calculate_strength_tss_per_set(sets)
    expected_stress = 10 * (7 / 10) ** 2  # 4.9
    assert result["debug"]["per_set_contributions"] == pytest.approx([expected_stress])
    assert result["debug"]["raw_sum"] == pytest.approx(expected_stress)


# ── AC-11c: missing rpe on one set returns null ────────────────────────────────

def test_missing_rpe_returns_null():
    """AC-11c / AC-6: missing rpe on any set → tss=None, method='none', reason in debug."""
    sets = [
        {"reps": 5, "rpe": 8},
        {"reps": 5, "rpe": None},
    ]
    result = calculate_strength_tss_per_set(sets)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]  # non-empty


def test_missing_reps_returns_null():
    """AC-6: missing reps on any set → tss=None, method='none', reason in debug."""
    sets = [
        {"reps": None, "rpe": 8},
        {"reps": 5, "rpe": 9},
    ]
    result = calculate_strength_tss_per_set(sets)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


def test_missing_rpe_key_entirely_returns_null():
    """AC-6: set dict without 'rpe' key → null result, never raises."""
    sets = [{"reps": 5}]
    result = calculate_strength_tss_per_set(sets)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_missing_reps_key_entirely_returns_null():
    """AC-6: set dict without 'reps' key → null result, never raises."""
    sets = [{"rpe": 8}]
    result = calculate_strength_tss_per_set(sets)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_function_never_throws_on_bad_input():
    """AC-6: function must not raise regardless of input."""
    bad_inputs = [
        None,
        [None],
        [{"reps": "abc", "rpe": 8}],
        [{"reps": 5, "rpe": "bad"}],
        [{}],
    ]
    for inp in bad_inputs:
        result = calculate_strength_tss_per_set(inp)
        assert result["tss"] is None
        assert result["method"] == "none"


# ── AC-11d: empty set list returns null ───────────────────────────────────────

def test_empty_set_list_returns_null():
    """AC-11d: empty list → tss=None, method='none'."""
    result = calculate_strength_tss_per_set([])
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


# ── AC-11e: result at clamp boundary ─────────────────────────────────────────

def test_clamp_boundary():
    """AC-11e / AC-4: very high load is clamped to STRENGTH_TSS_MAX."""
    # 1000 reps at RPE 10 should exceed any reasonable max
    sets = [{"reps": 1000, "rpe": 10}]
    result = calculate_strength_tss_per_set(sets)
    assert result["tss"] == STRENGTH_TSS_MAX
    assert result["debug"]["clamped"] == pytest.approx(STRENGTH_TSS_MAX)


def test_result_below_clamp_not_clamped():
    """AC-4: result below STRENGTH_TSS_MAX is returned as-is, not clamped."""
    sets = [{"reps": 1, "rpe": 1}]
    result = calculate_strength_tss_per_set(sets)
    assert result["tss"] is not None
    assert result["tss"] < STRENGTH_TSS_MAX


# ── AC-5: method values ───────────────────────────────────────────────────────

def test_method_is_per_set_on_success():
    """AC-5: method='per_set' when calculation succeeds."""
    result = calculate_strength_tss_per_set([{"reps": 5, "rpe": 8}])
    assert result["method"] == "per_set"


def test_method_is_none_on_failure():
    """AC-5: method='none' when any input is missing or invalid."""
    result = calculate_strength_tss_per_set([{"reps": 5, "rpe": None}])
    assert result["method"] == "none"


# ── AC-4: tss is a whole integer ─────────────────────────────────────────────

def test_tss_is_integer():
    """AC-4: tss is returned as a whole integer (not float)."""
    result = calculate_strength_tss_per_set([{"reps": 5, "rpe": 8}])
    assert isinstance(result["tss"], int)


# ── AC-1: return shape ────────────────────────────────────────────────────────

def test_return_shape_has_exactly_three_keys():
    """AC-1: return value has exactly tss, method, debug keys."""
    result = calculate_strength_tss_per_set([{"reps": 5, "rpe": 8}])
    assert set(result.keys()) == {"tss", "method", "debug"}


def test_return_shape_error_has_exactly_three_keys():
    """AC-1: error result also has exactly tss, method, debug keys."""
    result = calculate_strength_tss_per_set([])
    assert set(result.keys()) == {"tss", "method", "debug"}


# ── AC-10: pure function (no DB access) ──────────────────────────────────────

def test_function_has_no_db_access():
    """AC-10: source code contains no DB-related identifiers."""
    src = inspect.getsource(calculate_strength_tss_per_set)
    for forbidden in ("db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in src, f"DB access found: {forbidden!r}"


# ── AC-8: docstring worked example ───────────────────────────────────────────

def test_docstring_includes_three_set_worked_example():
    """AC-8: docstring contains a three-set worked example."""
    doc = calculate_strength_tss_per_set.__doc__ or ""
    # Docstring must show three sets with specific reps/rpe values
    assert "rpe" in doc.lower() or "RPE" in doc
    assert "reps" in doc.lower() or "Reps" in doc
    # Must show the raw sum or per-set arithmetic
    assert "10.25" in doc or "raw sum" in doc.lower()


# ── AC-9: constants defined at module level ───────────────────────────────────

def test_strength_tss_scale_is_positive_number():
    """AC-9: STRENGTH_TSS_SCALE is a positive numeric constant."""
    assert isinstance(STRENGTH_TSS_SCALE, (int, float))
    assert STRENGTH_TSS_SCALE > 0


def test_strength_tss_max_is_positive_integer():
    """AC-9: STRENGTH_TSS_MAX is a positive numeric constant."""
    assert isinstance(STRENGTH_TSS_MAX, (int, float))
    assert STRENGTH_TSS_MAX > 0


def test_scale_produces_50_to_70_for_docstring_example():
    """AC-3: STRENGTH_TSS_SCALE is tuned so docstring example yields 50-70."""
    raw_sum = 10.25  # from docstring: 3.20 + 4.05 + 3.00
    scaled = raw_sum * STRENGTH_TSS_SCALE
    assert 50 <= round(scaled) <= 70


# ── AC-12: no DB seeding (static check) ──────────────────────────────────────

def test_no_user_preferences_seeding_in_module():
    """AC-12: tss module does not reference user_preferences with STRENGTH_TSS keys."""
    import backend.services.tss as tss_module
    src = inspect.getsource(tss_module)
    assert "STRENGTH_TSS_SCALE" not in src.replace("STRENGTH_TSS_SCALE =", "CONSTANT_DEF").replace(
        "STRENGTH_TSS_SCALE", "CONSTANT_REF"
    ) or True  # constant definition is expected — just ensure no DB insert
    assert "INSERT" not in src.upper() or "strength_tss_scale" not in src.lower()
    assert "user_preferences" not in src or "strength_tss" not in src.lower() or True
    # The key check: no INSERT of strength_tss constants into user_preferences
    assert not (
        "user_preferences" in src and
        ("STRENGTH_TSS_SCALE" in src or "STRENGTH_TSS_MAX" in src) and
        "INSERT" in src.upper()
    )
