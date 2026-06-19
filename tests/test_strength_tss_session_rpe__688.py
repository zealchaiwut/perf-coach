"""Unit tests for issue #688: Add strength TSS via session-RPE method.

Tests the pure function calculate_strength_tss(session_rpe, duration_minutes,
set_data, user_preferences) and the thin caller get_strength_tss_for_workout.

AC coverage:
  AC-1  pure function exists and is documented with worked examples in docstring
  AC-2  session_intensity = session_rpe / user_preferences.strength_rpe_max
  AC-3  tss = session_intensity * session_intensity * (duration_minutes / 60) * 100
  AC-4  60 min at RPE 10 (rpe_max=10) returns tss = 100
  AC-5  60 min at RPE 7 (rpe_max=10) returns tss = 49
  AC-6  derived session RPE = reps-weighted average of per-set RPE values
  AC-7  tss=null, method="none", debug with reason when no RPE and no sets
  AC-8  return always: tss (int or null), method, estimated=True, debug
  AC-9  no hardcoded values; strength_rpe_max read from user_preferences
  AC-10 thin caller function get_strength_tss_for_workout exists separately
  AC-11 plain arithmetic only (no ** exponent operator in implementation)
"""
import inspect
import types

import pytest

from backend.services.strength_tss import (
    calculate_strength_tss,
    get_strength_tss_for_workout,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prefs(strength_rpe_max=10):
    return types.SimpleNamespace(strength_rpe_max=strength_rpe_max)


# ── AC-4: 60 min at RPE 10 → tss = 100 ──────────────────────────────────────

def test_60_min_rpe_10_returns_100():
    """AC-4: 60-minute session at RPE 10 with rpe_max=10 returns tss=100."""
    result = calculate_strength_tss(
        session_rpe=10,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(strength_rpe_max=10),
    )
    assert result["tss"] == 100


# ── AC-5: 60 min at RPE 7 → tss = 49 ────────────────────────────────────────

def test_60_min_rpe_7_returns_49():
    """AC-5: 60-minute session at RPE 7 with rpe_max=10 returns tss=49."""
    result = calculate_strength_tss(
        session_rpe=7,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(strength_rpe_max=10),
    )
    assert result["tss"] == 49


# ── AC-2: session_intensity = session_rpe / rpe_max ─────────────────────────

def test_session_intensity_is_rpe_over_rpe_max():
    """AC-2: session_intensity = session_rpe / strength_rpe_max."""
    result = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(strength_rpe_max=10),
    )
    assert result["debug"]["session_intensity"] == pytest.approx(8 / 10)


def test_session_intensity_uses_rpe_max_from_prefs():
    """AC-9: changing strength_rpe_max changes session_intensity (no hardcoded 10)."""
    result_10 = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(strength_rpe_max=10),
    )
    result_20 = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(strength_rpe_max=20),
    )
    # SI with rpe_max=10: 0.8 → tss=64
    # SI with rpe_max=20: 0.4 → tss=16
    assert result_10["tss"] != result_20["tss"]
    assert result_10["debug"]["session_intensity"] == pytest.approx(0.8)
    assert result_20["debug"]["session_intensity"] == pytest.approx(0.4)


# ── AC-3: tss formula ────────────────────────────────────────────────────────

def test_tss_formula_30min_rpe_10():
    """AC-3: 30-minute session at RPE 10 → tss = 1.0 * 1.0 * (30/60) * 100 = 50."""
    result = calculate_strength_tss(
        session_rpe=10,
        duration_minutes=30,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["tss"] == 50


def test_tss_formula_90min_rpe_5():
    """AC-3: 90-minute session at RPE 5 → 0.5 * 0.5 * 1.5 * 100 = 37.5 → 38."""
    result = calculate_strength_tss(
        session_rpe=5,
        duration_minutes=90,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["tss"] == 38


def test_tss_is_whole_integer():
    """AC-3: tss is always a whole integer, not a float."""
    result = calculate_strength_tss(
        session_rpe=7,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert isinstance(result["tss"], int)


# ── AC-8: return shape ────────────────────────────────────────────────────────

def test_return_shape_on_success():
    """AC-8: successful result has exactly tss, method, estimated, debug."""
    result = calculate_strength_tss(
        session_rpe=10,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert set(result.keys()) == {"tss", "method", "estimated", "debug"}


def test_return_shape_on_null():
    """AC-8: null result also has exactly tss, method, estimated, debug."""
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert set(result.keys()) == {"tss", "method", "estimated", "debug"}


def test_estimated_is_true_on_success():
    """AC-8: estimated is always True when method is session_rpe."""
    result = calculate_strength_tss(
        session_rpe=10,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["estimated"] is True


def test_estimated_is_true_on_null():
    """AC-8: estimated is always True even when tss is null."""
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["estimated"] is True


def test_method_is_session_rpe_on_success():
    """AC-8: method is 'session_rpe' when tss was computed."""
    result = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["method"] == "session_rpe"


def test_method_is_none_when_missing_inputs():
    """AC-8: method is 'none' when tss cannot be computed."""
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["method"] == "none"


# ── AC-6: derived session RPE from sets ──────────────────────────────────────

def test_derived_rpe_from_sets_weighted_average():
    """AC-6: derived RPE is the reps-weighted average of per-set RPE values.

    Sets: (RPE 8, 10 reps), (RPE 9, 8 reps), (RPE 7, 12 reps)
    weighted_avg = (8*10 + 9*8 + 7*12) / (10+8+12) = 236/30 ≈ 7.867
    """
    set_data = [
        {"rpe": 8, "reps": 10},
        {"rpe": 9, "reps": 8},
        {"rpe": 7, "reps": 12},
    ]
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=45,
        set_data=set_data,
        user_preferences=_prefs(),
    )
    expected_rpe = (8 * 10 + 9 * 8 + 7 * 12) / (10 + 8 + 12)
    expected_si = expected_rpe / 10
    expected_tss = round(expected_si * expected_si * (45 / 60) * 100)
    assert result["tss"] == expected_tss
    assert result["method"] == "session_rpe"
    assert result["estimated"] is True


def test_derived_rpe_source_is_derived():
    """AC-6: debug.session_rpe_source is 'derived' when RPE comes from sets."""
    set_data = [{"rpe": 8, "reps": 5}]
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=set_data,
        user_preferences=_prefs(),
    )
    assert result["debug"]["session_rpe_source"] == "derived"


def test_direct_rpe_takes_precedence_over_sets():
    """AC-6: when session_rpe is provided, set_data is not used for RPE."""
    set_data = [{"rpe": 10, "reps": 100}]  # would give RPE 10 if used
    result = calculate_strength_tss(
        session_rpe=7,
        duration_minutes=60,
        set_data=set_data,
        user_preferences=_prefs(),
    )
    assert result["tss"] == 49  # from session_rpe=7, not derived


def test_direct_rpe_source_is_direct():
    """AC-6: debug.session_rpe_source is 'direct' when session_rpe was provided."""
    result = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["debug"]["session_rpe_source"] == "direct"


def test_sets_with_missing_rpe_silently_excluded():
    """AC-6: set entries missing rpe are silently excluded from the weighted average."""
    set_data = [
        {"rpe": None, "reps": 5},   # excluded
        {"rpe": 8, "reps": 5},      # valid
    ]
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=set_data,
        user_preferences=_prefs(),
    )
    # Only the valid set: derived RPE = 8, tss = (0.8)^2 * 1 * 100 = 64
    assert result["tss"] == 64
    assert result["method"] == "session_rpe"


def test_sets_with_missing_reps_silently_excluded():
    """AC-6: set entries missing reps are silently excluded from the weighted average."""
    set_data = [
        {"rpe": 9, "reps": None},   # excluded
        {"rpe": 7, "reps": 10},     # valid
    ]
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=set_data,
        user_preferences=_prefs(),
    )
    assert result["tss"] == 49  # derived RPE=7, tss = 0.7^2 * 1 * 100 = 49


# ── AC-7: null when no RPE and no sets ───────────────────────────────────────

def test_null_when_no_rpe_and_no_sets():
    """AC-7: tss=null, method='none' when session_rpe is None and set_data is None."""
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


def test_null_when_no_rpe_and_empty_sets():
    """AC-7: tss=null when session_rpe is None and set_data is an empty list."""
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=[],
        user_preferences=_prefs(),
    )
    assert result["tss"] is None
    assert result["method"] == "none"


def test_null_when_all_sets_are_invalid():
    """AC-7: tss=null when all set entries are missing rpe or reps."""
    set_data = [
        {"rpe": None, "reps": 5},
        {"rpe": 8, "reps": None},
        {"other": "field"},
    ]
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=60,
        set_data=set_data,
        user_preferences=_prefs(),
    )
    assert result["tss"] is None
    assert result["method"] == "none"


def test_null_when_duration_is_none():
    """AC-7: tss=null when duration_minutes is None, even with a valid RPE."""
    result = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=None,
        set_data=None,
        user_preferences=_prefs(),
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert "duration" in result["debug"]["reason"].lower()


def test_null_when_duration_none_with_sets():
    """AC-7: tss=null when duration_minutes is None, even with valid set_data."""
    set_data = [{"rpe": 8, "reps": 5}]
    result = calculate_strength_tss(
        session_rpe=None,
        duration_minutes=None,
        set_data=set_data,
        user_preferences=_prefs(),
    )
    assert result["tss"] is None
    assert result["method"] == "none"


# ── AC-9: strength_rpe_max not configured → null ─────────────────────────────

def test_null_when_strength_rpe_max_not_configured():
    """AC-9: tss=null when user_preferences.strength_rpe_max is None."""
    result = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(strength_rpe_max=None),
    )
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]


def test_null_reason_mentions_rpe_max():
    """AC-9: reason string mentions the missing strength_rpe_max preference."""
    result = calculate_strength_tss(
        session_rpe=8,
        duration_minutes=60,
        set_data=None,
        user_preferences=_prefs(strength_rpe_max=None),
    )
    reason = result["debug"]["reason"].lower()
    assert "strength_rpe_max" in reason or "rpe_max" in reason or "rpe" in reason


# ── AC-1: docstring with worked examples ─────────────────────────────────────

def test_docstring_exists():
    """AC-1: calculate_strength_tss has a non-empty docstring."""
    assert calculate_strength_tss.__doc__, "docstring must be present"


def test_docstring_includes_rpe_10_worked_example():
    """AC-1: docstring contains the RPE 10, 60-min → tss=100 worked example."""
    doc = calculate_strength_tss.__doc__ or ""
    assert "100" in doc
    assert "1.0" in doc


def test_docstring_includes_rpe_7_worked_example():
    """AC-1: docstring contains the RPE 7, 60-min → tss=49 worked example."""
    doc = calculate_strength_tss.__doc__ or ""
    assert "49" in doc
    assert "0.7" in doc


# ── AC-1/AC-9: pure function ─────────────────────────────────────────────────

def test_function_has_no_db_access():
    """AC-1: calculate_strength_tss source contains no DB-related identifiers."""
    import ast
    src = inspect.getsource(calculate_strength_tss)
    tree = ast.parse(src)
    func_def = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    # Skip the docstring (first Expr node) so English prose with "session." doesn't false-positive
    body_start_idx = 1 if isinstance(func_def.body[0], ast.Expr) else 0
    body_start_line = func_def.body[body_start_idx].lineno - 1
    body = "\n".join(src.splitlines()[body_start_line:])
    for forbidden in ("db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in body, f"DB access found in calculate_strength_tss: {forbidden!r}"


# ── AC-11: plain arithmetic (no ** operator) ─────────────────────────────────

def test_no_exponent_operator_in_implementation():
    """AC-11: calculate_strength_tss uses multiplication, not ** for squaring."""
    import ast
    src = inspect.getsource(calculate_strength_tss)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            pytest.fail("calculate_strength_tss must not use ** (exponent operator); use x*x instead")


# ── AC-10: thin caller exists ────────────────────────────────────────────────

def test_thin_caller_is_importable():
    """AC-10: get_strength_tss_for_workout is importable from strength_tss module."""
    assert callable(get_strength_tss_for_workout)


def test_thin_caller_has_db_access():
    """AC-10: thin caller performs DB access (pure function does not)."""
    src = inspect.getsource(get_strength_tss_for_workout)
    assert any(
        keyword in src
        for keyword in ("db.", "db,", "execute(", "fetchone(", "fetchall(")
    ), "thin caller must perform DB access"


def test_thin_caller_delegates_to_pure_function():
    """AC-10: thin caller calls calculate_strength_tss."""
    src = inspect.getsource(get_strength_tss_for_workout)
    assert "calculate_strength_tss" in src
