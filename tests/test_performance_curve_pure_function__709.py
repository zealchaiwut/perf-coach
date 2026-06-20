"""
Tests for issue #709: Add performance_curve pure function to fitness model.

Acceptance criteria verified:
- AC1: performance_curve(fitness_series) exists in the fitness model module
       and performs no database access.
- AC2: Accepts CTL, ATL, TSB series as produced by compute_load_curves without
       recomputing them.
- AC3: Returns a list of per-day records with 'date', 'form' (TSB), 'zone' (string).
- AC4: Zone classification uses named band constants; zones are 'buried', 'neutral',
       'fresh'.
- AC5: Returns 'today_form' and 'today_zone' at the top level.
- AC6: When input is missing or empty, returns empty result with reason string; no
       exception raised.
- AC7: Docstring includes a worked example mapping TSB values to zone strings.
- AC8: Docstring uses plain words for comparisons (no carets, arrows, pipe-union).
- AC9: All zone band thresholds defined as named constants; no bare numeric
       literals in the function body.
- AC10: Unit tests cover normal multi-day series, empty input, today not in series,
        and boundary values at each zone threshold.
"""
import ast
import datetime
import inspect
import textwrap

import pytest

from backend.services.training_load import (
    FORM_BURIED_CEILING,
    FORM_FRESH_FLOOR,
    compute_load_curves,
    performance_curve,
)

TODAY = datetime.date.today()


def _make_series(tsb_values, start_date=None):
    """Build a minimal fitness_series with given TSB values, starting start_date days ago."""
    if start_date is None:
        start_date = TODAY - datetime.timedelta(days=len(tsb_values) - 1)
    return [
        {
            "date": start_date + datetime.timedelta(days=i),
            "ctl": 50.0,
            "atl": 50.0 - tsb,
            "tsb": tsb,
        }
        for i, tsb in enumerate(tsb_values)
    ]


# ── AC1: function exists in module and performs no DB access ──────────────────

def test_ac1_function_importable():
    """performance_curve is importable from the fitness model module."""
    assert callable(performance_curve)


def test_ac1_no_db_access_in_body():
    """performance_curve body must not call any DB/engine/session utilities."""
    src = inspect.getsource(performance_curve)
    for forbidden in ("engine", "Session", "connect", "execute", "daily_tss_series"):
        assert forbidden not in src, (
            f"performance_curve must not reference '{forbidden}' (no DB access)"
        )


# ── AC2: accepts compute_load_curves output without recomputing ───────────────

def test_ac2_accepts_compute_load_curves_output():
    """performance_curve accepts the direct output of compute_load_curves."""
    raw = [(TODAY - datetime.timedelta(days=i), i * 5) for i in range(10, -1, -1)]
    series = compute_load_curves(raw)
    result = performance_curve(series)
    assert result["reason"] == "", f"Unexpected reason: {result['reason']}"
    assert len(result["curve"]) == len(series)


def test_ac2_does_not_call_compute_load_curves_internally():
    """performance_curve body must not call compute_load_curves (it uses pre-computed data)."""
    src = inspect.getsource(performance_curve)
    tree = ast.parse(textwrap.dedent(src))
    func_body = tree.body[0].body
    # Skip docstring node
    if func_body and isinstance(func_body[0], ast.Expr) and isinstance(func_body[0].value, ast.Constant):
        func_body = func_body[1:]
    called = [
        node.func.id if isinstance(node.func, ast.Name) else
        node.func.attr if isinstance(node.func, ast.Attribute) else ""
        for node in ast.walk(ast.Module(body=func_body, type_ignores=[]))
        if isinstance(node, ast.Call) and hasattr(node, "func")
    ]
    assert "compute_load_curves" not in called
    assert "daily_tss_series" not in called


# ── AC3: per-day records contain date, form, zone ────────────────────────────

def test_ac3_curve_records_have_required_keys():
    """Every curve record has 'date', 'form', and 'zone' keys."""
    series = _make_series([10.0, -5.0, 2.0])
    result = performance_curve(series)
    for i, record in enumerate(result["curve"]):
        assert "date" in record, f"Record {i} missing 'date'"
        assert "form" in record, f"Record {i} missing 'form'"
        assert "zone" in record, f"Record {i} missing 'zone'"


def test_ac3_form_is_tsb_value_unmodified():
    """'form' in each record equals the original tsb value without modification."""
    tsb_values = [12.3, -8.7, 0.5]
    series = _make_series(tsb_values)
    result = performance_curve(series)
    for i, (record, expected_tsb) in enumerate(zip(result["curve"], tsb_values)):
        assert record["form"] == expected_tsb, (
            f"Record {i}: form {record['form']} != original tsb {expected_tsb}"
        )


def test_ac3_zone_is_string():
    """'zone' in each curve record is a string."""
    series = _make_series([10.0, -5.0, 2.0])
    result = performance_curve(series)
    for record in result["curve"]:
        assert isinstance(record["zone"], str), f"zone must be a string, got {type(record['zone'])}"


# ── AC4: zone classification uses named constants ─────────────────────────────

def test_ac4_buried_zone_below_ceiling():
    """TSB strictly below FORM_BURIED_CEILING yields zone 'buried'."""
    tsb = FORM_BURIED_CEILING - 1.0
    series = _make_series([tsb])
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "buried"


def test_ac4_fresh_zone_at_or_above_floor():
    """TSB at or above FORM_FRESH_FLOOR yields zone 'fresh'."""
    tsb = FORM_FRESH_FLOOR + 0.1
    series = _make_series([tsb])
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "fresh"


def test_ac4_neutral_zone_between_constants():
    """TSB in (FORM_BURIED_CEILING, FORM_FRESH_FLOOR) yields zone 'neutral'."""
    tsb = (FORM_BURIED_CEILING + FORM_FRESH_FLOOR) / 2.0
    series = _make_series([tsb])
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "neutral"


def test_ac4_zone_values_are_expected_strings():
    """Zone values are exactly one of 'buried', 'neutral', 'fresh'."""
    series = _make_series([FORM_BURIED_CEILING - 5, 0.0, FORM_FRESH_FLOOR + 5])
    result = performance_curve(series)
    zones = [r["zone"] for r in result["curve"]]
    assert zones == ["buried", "neutral", "fresh"]


# ── AC5: today_form and today_zone ────────────────────────────────────────────

def test_ac5_today_form_and_zone_in_result():
    """top-level keys 'today_form' and 'today_zone' are present."""
    series = _make_series([7.0])
    result = performance_curve(series)
    assert "today_form" in result
    assert "today_zone" in result


def test_ac5_today_form_matches_today_tsb():
    """today_form equals the TSB for today's date in the series."""
    today_tsb = FORM_FRESH_FLOOR + 4.0
    series = _make_series([-5.0, today_tsb])  # yesterday + today
    result = performance_curve(series)
    assert result["today_form"] == today_tsb


def test_ac5_today_zone_matches_today_tsb():
    """today_zone matches the zone derived from today's TSB."""
    today_tsb = FORM_BURIED_CEILING - 3.0
    series = _make_series([today_tsb])
    result = performance_curve(series)
    assert result["today_zone"] == "buried"


# ── AC6: missing/empty input → empty result + reason string ──────────────────

def test_ac6_none_input_returns_empty_curve():
    """None input yields empty curve and non-empty reason; no exception."""
    result = performance_curve(None)
    assert len(result.get("curve", [])) == 0
    assert result.get("reason"), "reason must be non-empty for None input"


def test_ac6_empty_list_returns_empty_curve():
    """Empty list yields empty curve and non-empty reason; no exception."""
    result = performance_curve([])
    assert len(result.get("curve", [])) == 0
    assert result.get("reason"), "reason must be non-empty for empty list input"


def test_ac6_no_exception_on_bad_inputs():
    """performance_curve never raises for None, empty list, or malformed records."""
    for bad in [None, [], [{"no_tsb": 1}], [{"date": TODAY}], [{"tsb": 5.0}]]:
        try:
            performance_curve(bad)
        except Exception as exc:
            pytest.fail(f"performance_curve raised {type(exc).__name__} for {bad!r}: {exc}")


# ── AC7: docstring has worked example mapping TSB values to zone strings ──────

def test_ac7_docstring_covers_all_three_zones():
    """Docstring worked example mentions 'buried', 'neutral', and 'fresh'."""
    doc = performance_curve.__doc__ or ""
    for zone in ("buried", "neutral", "fresh"):
        assert zone in doc.lower(), f"docstring must mention zone '{zone}'"


def test_ac7_docstring_maps_tsb_to_zone():
    """Docstring contains a concrete TSB value example."""
    doc = performance_curve.__doc__ or ""
    # A worked example must contain numeric TSB references
    has_number = any(char.isdigit() for char in doc)
    assert has_number, "docstring must include a worked example with numeric TSB values"


# ── AC8: docstring uses plain words (no carets/arrows/pipe-union) ─────────────

def test_ac8_no_carets_or_arrows_in_docstring():
    """Docstring must not use '<', '>', '->', '=>', or '|' for type/comparison notation."""
    doc = performance_curve.__doc__ or ""
    for forbidden in ("<", ">", "->", "=>", "|"):
        assert forbidden not in doc, (
            f"Docstring must not use '{forbidden}' — use plain words instead"
        )


# ── AC9: no bare numeric literals in function body ────────────────────────────

def test_ac9_no_bare_numeric_thresholds_in_function_body():
    """The _classify_zone helper (called by performance_curve) must not contain
    bare numeric threshold literals — only named constants."""
    from backend.services.training_load import _classify_zone
    src = inspect.getsource(_classify_zone)
    tree = ast.parse(textwrap.dedent(src))
    # Extract all numeric constants from the function body (skip docstring)
    func_body = tree.body[0].body
    if func_body and isinstance(func_body[0], ast.Expr) and isinstance(func_body[0].value, ast.Constant):
        func_body = func_body[1:]
    numeric_literals = [
        node.value
        for node in ast.walk(ast.Module(body=func_body, type_ignores=[]))
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
    ]
    # Only 0 is acceptable (e.g., for zero-comparisons); threshold values must not appear raw
    threshold_literals = [v for v in numeric_literals if v not in (0, 0.0)]
    assert threshold_literals == [], (
        f"_classify_zone contains bare threshold literals {threshold_literals}; "
        "use named constants instead"
    )


# ── AC10: normal multi-day series coverage ───────────────────────────────────

def test_ac10_normal_multi_day_series():
    """Normal 30-day series: curve length matches, all records well-formed."""
    series = _make_series([float(i - 10) for i in range(30)])
    result = performance_curve(series)
    assert result["reason"] == ""
    assert len(result["curve"]) == 30
    for record in result["curve"]:
        assert "date" in record and "form" in record and "zone" in record
        assert record["zone"] in ("buried", "neutral", "fresh")


def test_ac10_today_not_present_in_series():
    """When today is not in the series, today_form and today_zone are None."""
    past_start = TODAY - datetime.timedelta(days=5)
    series = _make_series([1.0, 2.0, 3.0], start_date=past_start)
    # series ends 3 days ago; today is not included
    result = performance_curve(series)
    assert result["today_form"] is None
    assert result["today_zone"] is None


def test_ac10_boundary_at_buried_ceiling():
    """TSB exactly at FORM_BURIED_CEILING maps to 'neutral' (not buried)."""
    tsb = FORM_BURIED_CEILING  # at the boundary, not below
    series = _make_series([tsb])
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "neutral", (
        f"TSB={tsb} (exactly at buried ceiling) should be 'neutral', not 'buried'"
    )


def test_ac10_boundary_just_below_buried_ceiling():
    """TSB just below FORM_BURIED_CEILING maps to 'buried'."""
    tsb = FORM_BURIED_CEILING - 0.001
    series = _make_series([tsb])
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "buried"


def test_ac10_boundary_at_fresh_floor():
    """TSB exactly at FORM_FRESH_FLOOR maps to 'fresh'."""
    tsb = FORM_FRESH_FLOOR  # at the boundary
    series = _make_series([tsb])
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "fresh", (
        f"TSB={tsb} (exactly at fresh floor) should be 'fresh'"
    )


def test_ac10_boundary_just_below_fresh_floor():
    """TSB just below FORM_FRESH_FLOOR maps to 'neutral'."""
    tsb = FORM_FRESH_FLOOR - 0.001
    series = _make_series([tsb])
    result = performance_curve(series)
    assert result["curve"][0]["zone"] == "neutral"
