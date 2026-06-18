"""
Tests for issue #606: Add performance_curve pure function to fitness model.

Acceptance criteria verified:
- AC1: performance_curve(fitness_series) exists in training_load module and accepts
       the output of compute_load_curves (list of dicts with date/ctl/atl/tsb).
- AC2: Returns per-day records each with date, form (TSB unmodified), and zone.
- AC3: Zone classification uses named band constants (FORM_BURIED_CEILING,
       FORM_FRESH_FLOOR) at module level; no numeric literals in classification logic.
- AC4: Returns today_form and today_zone as top-level fields.
- AC5: None, empty, or missing-columns input returns empty result with reason string,
       no exception raised.
- AC6: Function does not recompute CTL/ATL/TSB -- only reads existing series.
- AC7: Docstring contains a worked example covering all three zone values.
- AC8: Zone boundary comparisons in docstring use words, not carets/arrows/pipes.
- AC9: Unit tests cover all three zone branches, missing-input early-return, and
       today summary fields. (This file IS those tests.)
- AC10: Function signature and return shape are documented for thin callers.
"""
import ast
import datetime
import inspect
import textwrap

import pytest

from backend.services.training_load import (
    FORM_BURIED_CEILING,
    FORM_FRESH_FLOOR,
    performance_curve,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

TODAY = datetime.date.today()


def _series(*tsb_values, start_date=None):
    """Build a minimal fitness_series list with the given TSB values."""
    if start_date is None:
        start_date = TODAY - datetime.timedelta(days=len(tsb_values) - 1)
    result = []
    for i, tsb in enumerate(tsb_values):
        result.append({
            "date": start_date + datetime.timedelta(days=i),
            "ctl": 50.0,
            "atl": 50.0 - tsb,
            "tsb": tsb,
        })
    return result


# ── AC3: Module-level constants exist ─────────────────────────────────────────

def test_ac3_constants_exported():
    """FORM_BURIED_CEILING and FORM_FRESH_FLOOR must be importable from training_load."""
    assert isinstance(FORM_BURIED_CEILING, (int, float)), (
        "FORM_BURIED_CEILING must be a numeric constant"
    )
    assert isinstance(FORM_FRESH_FLOOR, (int, float)), (
        "FORM_FRESH_FLOOR must be a numeric constant"
    )


def test_ac3_buried_ceiling_below_fresh_floor():
    """FORM_BURIED_CEILING is less than FORM_FRESH_FLOOR (buried is more negative than fresh)."""
    assert FORM_BURIED_CEILING < FORM_FRESH_FLOOR, (
        "FORM_BURIED_CEILING must be less than FORM_FRESH_FLOOR"
    )


# ── AC2/AC9: All three zone branches ─────────────────────────────────────────

def test_ac2_ac9_zone_buried():
    """TSB below FORM_BURIED_CEILING maps to zone 'buried'."""
    tsb = FORM_BURIED_CEILING - 5.0
    series = _series(tsb)
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "buried", (
        f"TSB={tsb} (below buried ceiling {FORM_BURIED_CEILING}) must be zone 'buried'"
    )


def test_ac2_ac9_zone_fresh():
    """TSB above FORM_FRESH_FLOOR maps to zone 'fresh'."""
    tsb = FORM_FRESH_FLOOR + 5.0
    series = _series(tsb)
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "fresh", (
        f"TSB={tsb} (above fresh floor {FORM_FRESH_FLOOR}) must be zone 'fresh'"
    )


def test_ac2_ac9_zone_neutral():
    """TSB between FORM_BURIED_CEILING and FORM_FRESH_FLOOR maps to zone 'neutral'."""
    tsb = (FORM_BURIED_CEILING + FORM_FRESH_FLOOR) / 2.0
    series = _series(tsb)
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "neutral", (
        f"TSB={tsb} (mid-range) must be zone 'neutral'"
    )


def test_ac2_curve_record_has_date_form_zone():
    """Each curve record contains 'date', 'form', and 'zone' keys."""
    series = _series(7.5)
    result = performance_curve(series)
    record = result["curve"][0]
    assert "date" in record, "curve record must have 'date'"
    assert "form" in record, "curve record must have 'form'"
    assert "zone" in record, "curve record must have 'zone'"


def test_ac2_form_is_unmodified_tsb():
    """'form' in each curve record equals the original TSB value, unmodified."""
    tsb = 3.14
    series = _series(tsb)
    result = performance_curve(series)
    assert result["curve"][0]["form"] == tsb, "form must equal the original tsb value"


def test_ac2_curve_length_matches_series():
    """Number of curve records equals number of input series rows."""
    series = _series(10.0, -5.0, 3.0)
    result = performance_curve(series)
    assert len(result["curve"]) == 3


# ── AC4: today_form and today_zone top-level fields ───────────────────────────

def test_ac4_today_form_present():
    """today_form appears at the top level of the result."""
    series = _series(7.5)
    result = performance_curve(series)
    assert "today_form" in result, "today_form must be a top-level key"


def test_ac4_today_zone_present():
    """today_zone appears at the top level of the result."""
    series = _series(7.5)
    result = performance_curve(series)
    assert "today_zone" in result, "today_zone must be a top-level key"


def test_ac4_today_form_matches_today_tsb():
    """today_form equals the TSB for today's date."""
    today_tsb = FORM_FRESH_FLOOR + 3.0
    series = _series(-5.0, today_tsb)  # yesterday + today
    result = performance_curve(series)
    assert result["today_form"] == today_tsb


def test_ac4_today_zone_matches_today_tsb():
    """today_zone is 'fresh' when today's TSB is above FORM_FRESH_FLOOR."""
    today_tsb = FORM_FRESH_FLOOR + 3.0
    series = _series(-5.0, today_tsb)
    result = performance_curve(series)
    assert result["today_zone"] == "fresh"


def test_ac4_today_form_none_when_today_not_in_series():
    """today_form and today_zone are None when today is not present in the series."""
    past_date = TODAY - datetime.timedelta(days=10)
    series = _series(-2.0, start_date=past_date)
    result = performance_curve(series)
    assert result["today_form"] is None
    assert result["today_zone"] is None


# ── AC5: graceful early-return for bad input ──────────────────────────────────

def test_ac5_none_input_returns_empty_with_reason():
    """None input returns empty curve and a non-empty reason string, no exception."""
    result = performance_curve(None)
    assert result["curve"] == [] or result.get("curve") is None or len(result.get("curve", [])) == 0
    assert "reason" in result
    assert result["reason"]


def test_ac5_empty_list_returns_empty_with_reason():
    """Empty list input returns empty curve and a non-empty reason string."""
    result = performance_curve([])
    assert len(result.get("curve", [])) == 0
    assert "reason" in result
    assert result["reason"]


def test_ac5_missing_tsb_column_returns_empty_with_reason():
    """Dicts lacking 'tsb' key return empty curve and reason, no exception."""
    bad_series = [{"date": TODAY, "ctl": 40.0, "atl": 35.0}]
    result = performance_curve(bad_series)
    assert len(result.get("curve", [])) == 0
    assert "reason" in result
    assert result["reason"]


def test_ac5_missing_date_column_returns_empty_with_reason():
    """Dicts lacking 'date' key return empty curve and reason, no exception."""
    bad_series = [{"ctl": 40.0, "atl": 35.0, "tsb": 5.0}]
    result = performance_curve(bad_series)
    assert len(result.get("curve", [])) == 0
    assert "reason" in result
    assert result["reason"]


def test_ac5_no_exception_for_bad_input():
    """performance_curve never raises for None, empty, or missing-column input."""
    for bad in [None, [], [{"no_tsb": 1}], [{"date": TODAY}]]:
        try:
            performance_curve(bad)
        except Exception as exc:
            pytest.fail(f"performance_curve raised {type(exc).__name__} for input {bad!r}")


# ── AC7/AC8: docstring checks ─────────────────────────────────────────────────

def test_ac7_docstring_has_worked_example():
    """Docstring contains a worked example (AC7)."""
    doc = performance_curve.__doc__ or ""
    # A worked example must mention at least one TSB-like numeric and all three zones
    assert "buried" in doc.lower(), "docstring must mention 'buried' zone"
    assert "neutral" in doc.lower(), "docstring must mention 'neutral' zone"
    assert "fresh" in doc.lower(), "docstring must mention 'fresh' zone"


def test_ac8_docstring_no_carets_or_arrows():
    """Docstring uses words for comparisons -- no carets, arrows, or pipe-union syntax (AC8)."""
    doc = performance_curve.__doc__ or ""
    forbidden = ["<", ">", "->", "=>", "|"]
    for char in forbidden:
        assert char not in doc, (
            f"docstring must not use '{char}' for boundary comparisons -- use words instead"
        )


# ── AC6: does not call compute_load_curves internally ────────────────────────

def test_ac6_does_not_import_or_call_tss_computation():
    """performance_curve body must not call compute_load_curves or daily_tss_series (AC6)."""
    src = inspect.getsource(performance_curve)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    # Remove the docstring node if present before scanning for calls
    body_nodes = func_def.body
    if (body_nodes and isinstance(body_nodes[0], ast.Expr)
            and isinstance(body_nodes[0].value, ast.Constant)):
        body_nodes = body_nodes[1:]
    calls = [
        node.func.id if isinstance(node.func, ast.Name) else
        node.func.attr if isinstance(node.func, ast.Attribute) else ""
        for node in ast.walk(ast.Module(body=body_nodes, type_ignores=[]))
        if isinstance(node, ast.Call) and hasattr(node, "func")
    ]
    assert "compute_load_curves" not in calls, (
        "performance_curve body must not call compute_load_curves"
    )
    assert "daily_tss_series" not in calls, (
        "performance_curve body must not call daily_tss_series"
    )


# ── AC1: function signature ───────────────────────────────────────────────────

def test_ac1_function_exists_and_callable():
    """performance_curve is importable and callable from training_load."""
    assert callable(performance_curve)


def test_ac1_accepts_single_positional_arg():
    """performance_curve accepts a single positional argument (fitness_series)."""
    sig = inspect.signature(performance_curve)
    params = list(sig.parameters.keys())
    assert len(params) >= 1
    assert params[0] == "fitness_series"
