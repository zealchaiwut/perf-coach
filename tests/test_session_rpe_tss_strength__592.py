"""Tests for issue #592: Add session-RPE TSS method for strength sessions.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria covered:
  AC-1  — Function signature and return shape: tss, method, is_estimate, debug
  AC-2  — Formula: session_intensity = session_rpe/10; tss = si² × (duration_min/60) × 100
  AC-3  — 60-minute session at RPE 10 returns tss=100
  AC-4  — 60-minute session at RPE 7 returns tss=49
  AC-5  — Derived session RPE from reps-weighted set average when session_rpe absent
  AC-6  — debug always includes session_rpe_source, session_rpe, duration_minutes, session_intensity
  AC-7  — tss=null, method="none" when both session_rpe and usable sets are unavailable
  AC-8  — tss=null, method="none" when duration_minutes is null
  AC-9  — Set entries missing rpe or reps are silently excluded
  AC-10 — Pure function: no DB access
  AC-11 — No hardcoded threshold defaults inside the function
  AC-12 — Docstring includes both worked examples
"""
import inspect

import pytest

from backend.services.tss import calc_strength_tss


# ── AC-3: worked example — 60 min at RPE 10 → tss=100 ───────────────────────

def test_60_min_rpe_10_returns_tss_100():
    """AC-3: a 60-minute session at RPE 10 returns tss of 100."""
    result = calc_strength_tss(session_rpe=10, duration_minutes=60)
    assert result["tss"] == 100


# ── AC-4: worked example — 60 min at RPE 7 → tss=49 ─────────────────────────

def test_60_min_rpe_7_returns_tss_49():
    """AC-4: a 60-minute session at RPE 7 returns tss of 49."""
    result = calc_strength_tss(session_rpe=7, duration_minutes=60)
    assert result["tss"] == 49


# ── AC-2: formula correctness ─────────────────────────────────────────────────

def test_session_intensity_is_rpe_over_10():
    """AC-2: session_intensity = session_rpe / 10."""
    result = calc_strength_tss(session_rpe=8, duration_minutes=60)
    assert result["debug"]["session_intensity"] == pytest.approx(8 / 10)


def test_tss_formula_30min_rpe_10():
    """AC-2: 30-minute session at RPE 10 → si=1.0 → tss = 1.0² × 0.5 × 100 = 50."""
    result = calc_strength_tss(session_rpe=10, duration_minutes=30)
    assert result["tss"] == 50


def test_tss_formula_90min_rpe_5():
    """AC-2: 90-minute session at RPE 5 → si=0.5 → tss = 0.25 × 1.5 × 100 = 37 (rounded from 37.5)."""
    result = calc_strength_tss(session_rpe=5, duration_minutes=90)
    # 0.5^2 × (90/60) × 100 = 0.25 × 1.5 × 100 = 37.5 → 38
    assert result["tss"] == 38


def test_tss_is_whole_integer():
    """AC-2: tss is a whole integer, not a float."""
    result = calc_strength_tss(session_rpe=7, duration_minutes=60)
    assert isinstance(result["tss"], int)


# ── AC-1: return shape ────────────────────────────────────────────────────────

def test_return_shape_has_required_keys_on_success():
    """AC-1: success result has exactly tss, method, is_estimate, debug."""
    result = calc_strength_tss(session_rpe=10, duration_minutes=60)
    assert set(result.keys()) == {"tss", "method", "is_estimate", "debug"}


def test_return_shape_has_required_keys_on_failure():
    """AC-1: null result also has exactly tss, method, is_estimate, debug."""
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=None)
    assert set(result.keys()) == {"tss", "method", "is_estimate", "debug"}


def test_method_is_session_rpe_on_success():
    """AC-1: method is 'session_rpe' when tss is computed."""
    result = calc_strength_tss(session_rpe=10, duration_minutes=60)
    assert result["method"] == "session_rpe"


def test_is_estimate_true_when_session_rpe():
    """AC-1: is_estimate is True when method is 'session_rpe'."""
    result = calc_strength_tss(session_rpe=10, duration_minutes=60)
    assert result["is_estimate"] is True


def test_method_is_none_when_no_inputs():
    """AC-1: method is 'none' when tss cannot be computed."""
    result = calc_strength_tss(session_rpe=None, duration_minutes=60)
    assert result["method"] == "none"


# ── AC-5: derived session RPE from sets ──────────────────────────────────────

def test_sets_derived_rpe_weighted_average():
    """AC-5: when session_rpe absent, weighted avg RPE computed from sets.

    Sets: 5 reps@RPE8, 5 reps@RPE9, 3 reps@RPE10
    weighted_avg = (5*8 + 5*9 + 3*10) / 13 = 115/13 ≈ 8.846
    tss = (8.846/10)^2 × (60/60) × 100 ≈ 78.25 → 78
    """
    sets = [
        {"rpe": 8, "reps": 5},
        {"rpe": 9, "reps": 5},
        {"rpe": 10, "reps": 3},
    ]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    assert result["tss"] is not None
    assert result["method"] == "session_rpe"
    # weighted RPE = 115/13 ≈ 8.846; tss = (8.846/10)^2 × 1 × 100 ≈ 78
    expected_rpe = (5 * 8 + 5 * 9 + 3 * 10) / 13
    expected_tss = round((expected_rpe / 10) ** 2 * (60 / 60) * 100)
    assert result["tss"] == expected_tss


def test_sets_derived_method_is_still_session_rpe():
    """AC-5: method is 'session_rpe' even when RPE comes from sets."""
    sets = [{"rpe": 8, "reps": 5}]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    assert result["method"] == "session_rpe"


def test_sets_derived_is_estimate_true():
    """AC-5: is_estimate is True when derived from sets."""
    sets = [{"rpe": 8, "reps": 5}]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    assert result["is_estimate"] is True


def test_direct_session_rpe_takes_precedence_over_sets():
    """AC-5: when session_rpe is present, sets are not used for RPE derivation."""
    sets = [{"rpe": 10, "reps": 100}]  # would give RPE 10 if used
    result_direct = calc_strength_tss(session_rpe=7, duration_minutes=60, sets=sets)
    assert result_direct["tss"] == 49  # from session_rpe=7, not derived


def test_sets_derived_source_is_derived():
    """AC-5: debug.session_rpe_source is 'derived' when RPE comes from sets."""
    sets = [{"rpe": 8, "reps": 5}]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    assert result["debug"]["session_rpe_source"] == "derived"


# ── AC-6: debug fields ────────────────────────────────────────────────────────

def test_debug_has_all_required_fields_on_success():
    """AC-6: debug always includes session_rpe_source, session_rpe, duration_minutes, session_intensity."""
    result = calc_strength_tss(session_rpe=8, duration_minutes=60)
    debug = result["debug"]
    assert "session_rpe_source" in debug
    assert "session_rpe" in debug
    assert "duration_minutes" in debug
    assert "session_intensity" in debug


def test_debug_session_rpe_source_is_direct_when_provided():
    """AC-6: session_rpe_source is 'direct' when session_rpe was passed in."""
    result = calc_strength_tss(session_rpe=8, duration_minutes=60)
    assert result["debug"]["session_rpe_source"] == "direct"


def test_debug_contains_session_rpe_value_used():
    """AC-6: debug.session_rpe contains the actual RPE value used in calculation."""
    result = calc_strength_tss(session_rpe=7, duration_minutes=60)
    assert result["debug"]["session_rpe"] == pytest.approx(7)


def test_debug_contains_duration_minutes_used():
    """AC-6: debug.duration_minutes contains the duration used."""
    result = calc_strength_tss(session_rpe=7, duration_minutes=45)
    assert result["debug"]["duration_minutes"] == pytest.approx(45)


def test_debug_contains_session_intensity():
    """AC-6: debug.session_intensity = session_rpe / 10."""
    result = calc_strength_tss(session_rpe=8, duration_minutes=60)
    assert result["debug"]["session_intensity"] == pytest.approx(0.8)


# ── AC-7: null when no session_rpe and no usable sets ────────────────────────

def test_null_when_no_session_rpe_and_no_sets():
    """AC-7: tss=null, method='none' when both session_rpe and sets are absent."""
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=None)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


def test_null_when_no_session_rpe_and_empty_sets():
    """AC-7: tss=null, method='none' when session_rpe absent and sets is empty list."""
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=[])
    assert result["tss"] is None
    assert result["method"] == "none"


def test_null_when_sets_all_invalid():
    """AC-7: tss=null when all set entries are missing rpe or reps (no valid sets remain)."""
    sets = [{"rpe": None, "reps": 5}, {"rpe": 8, "reps": None}, {"other": "field"}]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    assert result["tss"] is None
    assert result["method"] == "none"


# ── AC-8: null when duration_minutes is null ──────────────────────────────────

def test_null_when_duration_minutes_is_none():
    """AC-8: tss=null, method='none' when duration_minutes is None."""
    result = calc_strength_tss(session_rpe=8, duration_minutes=None)
    assert result["tss"] is None
    assert result["method"] == "none"
    assert "reason" in result["debug"]
    assert "duration" in result["debug"]["reason"].lower()


def test_null_when_duration_minutes_is_none_even_with_sets():
    """AC-8: duration_minutes=None → null regardless of whether sets are present."""
    sets = [{"rpe": 8, "reps": 5}]
    result = calc_strength_tss(session_rpe=None, duration_minutes=None, sets=sets)
    assert result["tss"] is None
    assert result["method"] == "none"


# ── AC-9: invalid set entries silently excluded ───────────────────────────────

def test_sets_missing_rpe_silently_excluded():
    """AC-9: set entries without rpe are silently excluded, no error thrown."""
    sets = [
        {"rpe": None, "reps": 5},  # invalid — no rpe
        {"rpe": 8, "reps": 5},     # valid
    ]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    # Only the valid set contributes: RPE=8, tss = (8/10)^2 × 1 × 100 = 64
    assert result["tss"] == 64
    assert result["method"] == "session_rpe"


def test_sets_missing_reps_silently_excluded():
    """AC-9: set entries without reps are silently excluded, no error thrown."""
    sets = [
        {"rpe": 9, "reps": None},  # invalid — no reps
        {"rpe": 7, "reps": 10},    # valid
    ]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    # Only the valid set: RPE=7, tss = (7/10)^2 × 1 × 100 = 49
    assert result["tss"] == 49


def test_mixed_valid_invalid_sets_no_exception():
    """AC-9: mix of valid and invalid sets does not raise any exception."""
    sets = [
        {"rpe": 8, "reps": 5},
        {"other_key": "value"},     # missing rpe and reps
        {"rpe": 9},                 # missing reps
        {"reps": 3},                # missing rpe
    ]
    result = calc_strength_tss(session_rpe=None, duration_minutes=60, sets=sets)
    # Only first set is valid: RPE=8
    assert result["tss"] == 64
    assert result["method"] == "session_rpe"


# ── AC-10: pure function (static analysis) ───────────────────────────────────

def test_function_has_no_db_access():
    """AC-10: calc_strength_tss source contains no DB-related identifiers."""
    import ast
    src = inspect.getsource(calc_strength_tss)
    # Strip the docstring so "session." in English prose doesn't false-positive.
    tree = ast.parse(src)
    func_def = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    body_start = func_def.body[0].end_lineno if isinstance(func_def.body[0], ast.Expr) else func_def.body[0].lineno - 1
    body_lines = src.splitlines()[body_start:]
    body = "\n".join(body_lines)
    for forbidden in ("db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in body, f"DB access found: {forbidden!r}"


# ── AC-11: no hardcoded thresholds ───────────────────────────────────────────

def test_function_has_no_hardcoded_threshold_constants():
    """AC-11: function body contains no hardcoded numeric threshold defaults."""
    src = inspect.getsource(calc_strength_tss)
    # The function should not reference module-level threshold constants like FTP_W, THRESHOLD_HR
    assert "FTP_W" not in src
    assert "THRESHOLD_HR" not in src
    assert "THRESHOLD_PACE" not in src


# ── AC-12: docstring worked examples ─────────────────────────────────────────

def test_docstring_includes_rpe_10_worked_example():
    """AC-12: docstring contains the RPE 10, 60-min → tss=100 worked example."""
    doc = calc_strength_tss.__doc__ or ""
    assert "100" in doc
    assert "10" in doc
    assert "1.0" in doc


def test_docstring_includes_rpe_7_worked_example():
    """AC-12: docstring contains the RPE 7, 60-min → tss=49 worked example."""
    doc = calc_strength_tss.__doc__ or ""
    assert "49" in doc
    assert "0.7" in doc
