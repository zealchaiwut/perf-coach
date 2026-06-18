"""
Tests for issue #607: Add forward form projection to a target date.

Acceptance criteria verified:
- AC1: project_form(fitness_state, planned_daily_load, target_date) exists in
       training_load module with no direct DB calls inside it.
- AC2: fitness_state accepts at minimum { ctl, atl, date } where date is the
       anchor day for the projection.
- AC3: planned_daily_load accepts a single scalar (uniform) or an ordered
       list of per-day load values.
- AC4: Function uses named time constants CTL_DAYS and ATL_DAYS — no magic
       numbers in implementation.
- AC5: planned_daily_load=None falls back to caller-supplied recent_avg_load
       and sets assumed_load=True on every returned day object.
- AC6: Missing or invalid required inputs return empty list + reason string,
       no exception raised.
- AC7: Return value is a list of day objects each containing
       { date, ctl, atl, form, assumed_load }.
- AC8: Docstring includes a worked example showing form rising as atl decays
       faster than ctl under a flat load below both.
- AC9: get_projected_form thin caller exists and performs DB access.
- AC10: Unit tests cover flat load, per-day list, assumed_load flag, empty
        result on bad input, CTL/ATL values match manual computation.
- AC11: project_form imports and reuses CTL_DAYS, ATL_DAYS, _ewma_alpha from
        the module; no duplication of constants or update logic.
"""
import ast
import inspect
import textwrap
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from backend.services.training_load import (
    ATL_DAYS,
    CTL_DAYS,
    _ewma_alpha,
    get_projected_form,
    project_form,
)

TODAY = date.today()
ANCHOR = TODAY
TARGET_3 = ANCHOR + timedelta(days=3)
TARGET_5 = ANCHOR + timedelta(days=5)


def _state(ctl=50.0, atl=60.0, anchor=None):
    return {"ctl": ctl, "atl": atl, "date": anchor or ANCHOR}


# ── AC4: named constants exist and are exported ───────────────────────────────

def test_ac4_ctl_days_exported():
    assert isinstance(CTL_DAYS, int), "CTL_DAYS must be an integer constant"
    assert CTL_DAYS > 0


def test_ac4_atl_days_exported():
    assert isinstance(ATL_DAYS, int), "ATL_DAYS must be an integer constant"
    assert ATL_DAYS > 0


def test_ac4_ctl_days_greater_than_atl_days():
    assert CTL_DAYS > ATL_DAYS, "CTL_DAYS must be greater than ATL_DAYS"


def test_ac4_no_magic_numbers_in_project_form():
    """project_form body must not contain 42 or 7 as numeric literals."""
    src = inspect.getsource(project_form)
    tree = ast.parse(textwrap.dedent(src))
    # Skip the function def header lines; walk the body for integer constants
    func_def = tree.body[0]
    body = func_def.body
    # Remove docstring if present
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    magic_numbers = {42, 7}
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            assert node.value not in magic_numbers, (
                f"project_form body contains magic number {node.value}; "
                f"use CTL_DAYS/ATL_DAYS constants instead"
            )


# ── AC1: function exists and is pure (no DB calls in body) ───────────────────

def test_ac1_project_form_callable():
    assert callable(project_form)


def test_ac1_project_form_no_db_calls():
    """project_form must not call engine, Session, or daily_tss_series."""
    src = inspect.getsource(project_form)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]

    db_names = {"engine", "Session", "daily_tss_series", "current_load"}
    calls_found = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in db_names:
                calls_found.append(name)
    assert not calls_found, (
        f"project_form body calls DB functions: {calls_found}"
    )


# ── AC6: invalid / missing inputs return empty list + reason, no raise ────────

@pytest.mark.parametrize("fitness_state,target_date", [
    (None, TARGET_3),
    (_state(), None),
    ({}, TARGET_3),
    ({"ctl": 50.0, "atl": 60.0}, TARGET_3),   # missing date key
    ({"ctl": 50.0, "date": ANCHOR}, TARGET_3), # missing atl key
])
def test_ac6_invalid_required_input_returns_empty(fitness_state, target_date):
    result = project_form(fitness_state, 40.0, target_date)
    assert isinstance(result, dict), "project_form must return a dict"
    assert result.get("days") == [] or len(result.get("days", [])) == 0
    assert result.get("reason"), f"reason must be non-empty for invalid input {fitness_state!r}"


def test_ac6_target_date_not_after_anchor_returns_empty():
    result = project_form(_state(), 40.0, ANCHOR)
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac6_target_before_anchor_returns_empty():
    result = project_form(_state(), 40.0, ANCHOR - timedelta(days=1))
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac6_no_exception_for_bad_inputs():
    for bad in [
        (None, 40.0, TARGET_3),
        (_state(), 40.0, None),
        ({}, 40.0, TARGET_3),
    ]:
        try:
            project_form(*bad)
        except Exception as exc:
            pytest.fail(f"project_form raised {type(exc).__name__} for input {bad!r}")


# ── AC7: return shape — list of day objects with required keys ────────────────

def test_ac7_return_contains_days_list():
    result = project_form(_state(), 40.0, TARGET_3)
    assert "days" in result, "result must have 'days' key"
    assert isinstance(result["days"], list)


def test_ac7_return_contains_reason_string():
    result = project_form(_state(), 40.0, TARGET_3)
    assert "reason" in result, "result must have 'reason' key"
    assert isinstance(result["reason"], str)


def test_ac7_day_object_has_required_keys():
    result = project_form(_state(), 40.0, TARGET_3)
    assert result["days"], "expected at least one day in output"
    day = result["days"][0]
    for key in ("date", "ctl", "atl", "form", "assumed_load"):
        assert key in day, f"day object missing required key '{key}'"


def test_ac7_days_count_equals_distance_to_target():
    result = project_form(_state(), 40.0, TARGET_5)
    assert len(result["days"]) == 5, (
        f"expected 5 days from anchor+1 to target, got {len(result['days'])}"
    )


def test_ac7_first_day_is_anchor_plus_one():
    result = project_form(_state(anchor=ANCHOR), 40.0, TARGET_3)
    assert result["days"][0]["date"] == ANCHOR + timedelta(days=1)


def test_ac7_last_day_is_target_date():
    result = project_form(_state(anchor=ANCHOR), 40.0, TARGET_3)
    assert result["days"][-1]["date"] == TARGET_3


def test_ac7_success_reason_is_empty_string():
    result = project_form(_state(), 40.0, TARGET_3)
    assert result["reason"] == "", "reason must be empty string on success"


# ── AC2: fitness_state requires ctl, atl, date ───────────────────────────────

def test_ac2_accepts_ctl_atl_date_state():
    result = project_form({"ctl": 45.0, "atl": 50.0, "date": ANCHOR}, 40.0, TARGET_3)
    assert len(result["days"]) == 3


# ── AC3: flat scalar load ─────────────────────────────────────────────────────

def test_ac3_scalar_load_projects_correctly():
    result = project_form(_state(), 40.0, TARGET_3)
    assert len(result["days"]) == 3
    # All days use the same load, none assumed
    for day in result["days"]:
        assert day["assumed_load"] is False


def test_ac3_scalar_load_assumed_load_is_false():
    result = project_form(_state(), 50.0, TARGET_5)
    for day in result["days"]:
        assert day["assumed_load"] is False


# ── AC3: per-day list load ────────────────────────────────────────────────────

def test_ac3_list_load_exact_length():
    loads = [30.0, 50.0, 0.0]
    result = project_form(_state(), loads, TARGET_3)
    assert len(result["days"]) == 3
    for day in result["days"]:
        assert day["assumed_load"] is False


def test_ac3_list_load_shorter_than_target_pads_with_zero():
    loads = [30.0]  # only 1 value, target is 3 days away
    result = project_form(_state(), loads, TARGET_3)
    assert len(result["days"]) == 3
    assert result["days"][0]["assumed_load"] is False
    assert result["days"][1]["assumed_load"] is True
    assert result["days"][2]["assumed_load"] is True


def test_ac3_list_load_different_days_produce_different_atl():
    loads = [100.0, 0.0, 100.0]
    result = project_form(_state(), loads, TARGET_3)
    assert result["days"][0]["atl"] != result["days"][1]["atl"], (
        "high-load day and rest day should produce different ATL"
    )


# ── AC5: None planned_daily_load → assumed_load flag + recent_avg_load ────────

def test_ac5_none_load_uses_recent_avg_load():
    result = project_form(_state(), None, TARGET_3, recent_avg_load=40.0)
    assert len(result["days"]) == 3


def test_ac5_none_load_sets_assumed_load_true():
    result = project_form(_state(), None, TARGET_3, recent_avg_load=40.0)
    for day in result["days"]:
        assert day["assumed_load"] is True, (
            "assumed_load must be True when planned_daily_load is None"
        )


def test_ac5_none_load_without_recent_avg_returns_empty():
    result = project_form(_state(), None, TARGET_3)
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac5_assumed_load_false_when_scalar_provided():
    result = project_form(_state(), 40.0, TARGET_3, recent_avg_load=40.0)
    for day in result["days"]:
        assert day["assumed_load"] is False, (
            "assumed_load must be False when explicit planned_daily_load is provided"
        )


# ── AC10: CTL/ATL on day N matches manually computed values ───────────────────

def test_ac10_day1_ctl_atl_match_ewma_formula():
    """Day-1 CTL and ATL must equal the EWMA update using CTL_DAYS / ATL_DAYS."""
    ctl_0 = 50.0
    atl_0 = 60.0
    load = 40.0
    alpha_ctl = _ewma_alpha(CTL_DAYS)
    alpha_atl = _ewma_alpha(ATL_DAYS)

    expected_ctl1 = ctl_0 + (load - ctl_0) * alpha_ctl
    expected_atl1 = atl_0 + (load - atl_0) * alpha_atl

    result = project_form({"ctl": ctl_0, "atl": atl_0, "date": ANCHOR}, load, ANCHOR + timedelta(days=1))
    day1 = result["days"][0]

    assert abs(day1["ctl"] - round(expected_ctl1, 2)) < 0.005, (
        f"CTL day 1: expected {round(expected_ctl1,2)}, got {day1['ctl']}"
    )
    assert abs(day1["atl"] - round(expected_atl1, 2)) < 0.005, (
        f"ATL day 1: expected {round(expected_atl1,2)}, got {day1['atl']}"
    )


def test_ac10_form_equals_ctl_minus_atl():
    """form must be within rounding tolerance of ctl - atl on every projected day.

    form is computed from the precise floats then rounded to 2 dp, while the
    stored ctl and atl are also rounded independently.  This can cause a
    difference of up to 0.01 between form and round(ctl-atl, 2).
    """
    result = project_form(_state(), 40.0, TARGET_5)
    for day in result["days"]:
        assert abs(day["form"] - (day["ctl"] - day["atl"])) < 0.02, (
            f"form={day['form']} diverges too far from ctl-atl={day['ctl']}-{day['atl']}"
        )


def test_ac10_day2_ctl_atl_match_chain():
    """Day-2 values must chain off day-1 values (not off anchor)."""
    ctl_0 = 50.0
    atl_0 = 60.0
    load = 40.0
    alpha_ctl = _ewma_alpha(CTL_DAYS)
    alpha_atl = _ewma_alpha(ATL_DAYS)

    ctl1 = ctl_0 + (load - ctl_0) * alpha_ctl
    atl1 = atl_0 + (load - atl_0) * alpha_atl
    expected_ctl2 = ctl1 + (load - ctl1) * alpha_ctl
    expected_atl2 = atl1 + (load - atl1) * alpha_atl

    result = project_form(
        {"ctl": ctl_0, "atl": atl_0, "date": ANCHOR}, load, ANCHOR + timedelta(days=2)
    )
    day2 = result["days"][1]

    assert abs(day2["ctl"] - round(expected_ctl2, 2)) < 0.005
    assert abs(day2["atl"] - round(expected_atl2, 2)) < 0.005


def test_ac10_per_day_list_day1_uses_first_list_value():
    """With a per-day list, day 1 uses loads[0] not loads[1]."""
    ctl_0 = 50.0
    atl_0 = 60.0
    loads = [10.0, 100.0, 50.0]
    alpha_ctl = _ewma_alpha(CTL_DAYS)
    alpha_atl = _ewma_alpha(ATL_DAYS)

    expected_ctl1 = ctl_0 + (loads[0] - ctl_0) * alpha_ctl
    expected_atl1 = atl_0 + (loads[0] - atl_0) * alpha_atl

    result = project_form({"ctl": ctl_0, "atl": atl_0, "date": ANCHOR}, loads, ANCHOR + timedelta(days=3))
    day1 = result["days"][0]

    assert abs(day1["ctl"] - round(expected_ctl1, 2)) < 0.005
    assert abs(day1["atl"] - round(expected_atl1, 2)) < 0.005


def test_ac10_flat_load_below_atl_form_rises():
    """With load below ATL, form must rise each day (fatigue decays faster)."""
    # CTL=50, ATL=70 (form=-20), load=20 (below both)
    # ATL decays faster → form (CTL - ATL) rises each day
    result = project_form({"ctl": 50.0, "atl": 70.0, "date": ANCHOR}, 20.0, ANCHOR + timedelta(days=5))
    forms = [d["form"] for d in result["days"]]
    for i in range(1, len(forms)):
        assert forms[i] > forms[i - 1], (
            f"form should rise on day {i+1} ({forms[i]}) vs day {i} ({forms[i-1]}) "
            "when load is below ATL"
        )


# ── AC8: docstring contains a worked example ──────────────────────────────────

def test_ac8_docstring_has_worked_example():
    doc = project_form.__doc__ or ""
    assert len(doc.strip()) > 0, "project_form must have a docstring"
    # Worked example must show ctl, atl, form (TSB) rising
    assert "ctl" in doc.lower(), "docstring must mention ctl"
    assert "atl" in doc.lower(), "docstring must mention atl"
    assert "form" in doc.lower() or "tsb" in doc.lower(), "docstring must mention form/TSB"


def test_ac8_docstring_mentions_form_rises():
    doc = (project_form.__doc__ or "").lower()
    # Must illustrate that form rises when load is below ATL
    assert "rise" in doc or "rises" in doc or "higher" in doc or "increas" in doc, (
        "docstring worked example must illustrate that form rises over several days"
    )


# ── AC9: thin caller get_projected_form exists ───────────────────────────────

def test_ac9_get_projected_form_callable():
    assert callable(get_projected_form)


def test_ac9_thin_caller_calls_project_form():
    """get_projected_form must delegate to project_form."""
    with (
        patch("backend.services.training_load.current_load") as mock_cl,
        patch("backend.services.training_load.daily_tss_series") as mock_tss,
        patch("backend.services.training_load.project_form") as mock_pf,
    ):
        mock_cl.return_value = {"ctl": 50.0, "atl": 60.0, "date": TODAY}
        mock_tss.return_value = [(TODAY - timedelta(days=i), 50) for i in range(28)]
        mock_pf.return_value = {"days": [], "reason": ""}
        get_projected_form("user-1", None, TARGET_3)
        mock_pf.assert_called_once()


def test_ac9_thin_caller_passes_db_state_to_project_form():
    """get_projected_form must pass the fitness state fetched from DB."""
    with (
        patch("backend.services.training_load.current_load") as mock_cl,
        patch("backend.services.training_load.daily_tss_series") as mock_tss,
        patch("backend.services.training_load.project_form") as mock_pf,
    ):
        mock_cl.return_value = {"ctl": 44.0, "atl": 52.0, "date": TODAY}
        mock_tss.return_value = [(TODAY - timedelta(days=i), 60) for i in range(28)]
        mock_pf.return_value = {"days": [], "reason": ""}

        get_projected_form("user-1", None, TARGET_3)

        call_kwargs = mock_pf.call_args
        fitness_state = call_kwargs[0][0]  # first positional arg
        assert fitness_state["ctl"] == 44.0
        assert fitness_state["atl"] == 52.0


def test_ac9_thin_caller_computes_recent_avg_when_load_is_none():
    """When planned_daily_load=None, thin caller must supply recent_avg_load."""
    with (
        patch("backend.services.training_load.current_load") as mock_cl,
        patch("backend.services.training_load.daily_tss_series") as mock_tss,
        patch("backend.services.training_load.project_form") as mock_pf,
    ):
        mock_cl.return_value = {"ctl": 50.0, "atl": 60.0, "date": TODAY}
        # 28 days × 70 TSS/day → avg = 70
        mock_tss.return_value = [(TODAY - timedelta(days=i), 70) for i in range(28)]
        mock_pf.return_value = {"days": [], "reason": ""}

        get_projected_form("user-1", None, TARGET_3)

        call_kwargs = mock_pf.call_args
        # recent_avg_load should be passed as keyword arg
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        recent_avg = kwargs.get("recent_avg_load")
        assert recent_avg is not None, "thin caller must supply recent_avg_load"
        assert abs(recent_avg - 70.0) < 1.0, (
            f"expected recent_avg_load≈70, got {recent_avg}"
        )


def test_ac9_thin_caller_does_not_query_db_when_load_provided():
    """When planned_daily_load is provided, thin caller need not fetch TSS history."""
    with (
        patch("backend.services.training_load.current_load") as mock_cl,
        patch("backend.services.training_load.daily_tss_series") as mock_tss,
        patch("backend.services.training_load.project_form") as mock_pf,
    ):
        mock_cl.return_value = {"ctl": 50.0, "atl": 60.0, "date": TODAY}
        mock_pf.return_value = {"days": [], "reason": ""}

        get_projected_form("user-1", 50.0, TARGET_3)

        mock_tss.assert_not_called()


# ── AC11: project_form reuses _ewma_alpha — does not redefine EWMA math ──────

def test_ac11_project_form_calls_ewma_alpha():
    """project_form must call _ewma_alpha rather than reimplement the math."""
    src = inspect.getsource(project_form)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    call_names = [
        node.func.id if isinstance(node.func, ast.Name) else
        node.func.attr if isinstance(node.func, ast.Attribute) else ""
        for node in ast.walk(ast.Module(body=body, type_ignores=[]))
        if isinstance(node, ast.Call) and hasattr(node, "func")
    ]
    assert "_ewma_alpha" in call_names, (
        "project_form must call _ewma_alpha to reuse the shared update formula"
    )
