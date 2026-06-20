"""
Tests for issue #711: Add taper_recommendation function for race date guidance.

Acceptance criteria verified:
- AC1: Named constants defined for A-race taper length, B-race mini-taper
       length, and the positive target form band (lower and upper bounds).
- AC2: taper_recommendation is a pure function (no DB access or hardcoded
       numeric thresholds in function logic).
- AC3: Function accepts a priority field on fitness_state (or as a separate
       param) to distinguish A vs B races and select the correct taper length.
- AC4: Returns taper_start_date (date) and message (str) on valid input.
- AC5: Returns null taper_start_date plus a reason string on missing/invalid
       input.
- AC6: When achievable, taper_start_date = race_date minus the priority-
       appropriate taper length constant.
- AC7: When race too close, taper_start_date is None and message states form
       cannot be reached in time.
- AC8: Delegates form projection to existing project_form (no inline EWMA).
- AC9: Docstring includes two worked examples (normal A-race, too close).
- AC10: All numeric thresholds and lengths reference named constants.
- AC11: Unit tests: normal A-race taper, B-race mini-taper, race too close,
        missing inputs returning null with reason.
"""
import ast
import inspect
import textwrap
from datetime import date, timedelta

import pytest

from backend.services.training_load import (
    A_RACE_TAPER_DAYS,
    B_RACE_TAPER_DAYS,
    TARGET_FORM_LOWER,
    TARGET_FORM_UPPER,
    taper_recommendation,
)

TODAY = date.today()
RACE_28 = TODAY + timedelta(days=28)  # plenty of time for A or B taper
RACE_3 = TODAY + timedelta(days=3)    # too close to reach positive form band


def _state(ctl=50.0, atl=30.0, anchor=None, priority=None):
    s = {"ctl": ctl, "atl": atl, "date": anchor or TODAY}
    if priority is not None:
        s["priority"] = priority
    return s


def _state_high_fatigue(anchor=None, priority=None):
    """Deep negative form state so even 28 days won't recover for RACE_3."""
    s = {"ctl": 50.0, "atl": 90.0, "date": anchor or TODAY}
    if priority is not None:
        s["priority"] = priority
    return s


# ── AC1: named constants exported ────────────────────────────────────────────

def test_ac1_a_race_taper_days_is_int():
    assert isinstance(A_RACE_TAPER_DAYS, int)
    assert A_RACE_TAPER_DAYS > 0


def test_ac1_b_race_taper_days_is_int():
    assert isinstance(B_RACE_TAPER_DAYS, int)
    assert B_RACE_TAPER_DAYS > 0


def test_ac1_b_race_taper_days_shorter_than_a_race():
    """Mini-taper must be shorter than the full A-race taper."""
    assert B_RACE_TAPER_DAYS < A_RACE_TAPER_DAYS


def test_ac1_target_form_lower_positive():
    assert isinstance(TARGET_FORM_LOWER, float)
    assert TARGET_FORM_LOWER > 0


def test_ac1_target_form_upper_above_lower():
    assert isinstance(TARGET_FORM_UPPER, float)
    assert TARGET_FORM_UPPER > TARGET_FORM_LOWER


# ── AC2: pure function — no DB calls in body ─────────────────────────────────

def test_ac2_taper_recommendation_callable():
    assert callable(taper_recommendation)


def test_ac2_no_db_calls_in_body():
    src = inspect.getsource(taper_recommendation)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    # strip docstring
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
    assert not calls_found, f"taper_recommendation body calls DB functions: {calls_found}"


# ── AC3: priority field selects correct taper length ─────────────────────────

def test_ac3_a_race_priority_uses_a_race_taper_days():
    result = taper_recommendation(_state(priority="A"), RACE_28, 10.0)
    expected = RACE_28 - timedelta(days=A_RACE_TAPER_DAYS)
    assert result["taper_start_date"] == expected, (
        f"A-race taper_start_date should be {A_RACE_TAPER_DAYS} days before race"
    )


def test_ac3_b_race_priority_uses_b_race_taper_days():
    result = taper_recommendation(_state(priority="B"), RACE_28, 10.0)
    expected = RACE_28 - timedelta(days=B_RACE_TAPER_DAYS)
    assert result["taper_start_date"] == expected, (
        f"B-race taper_start_date should be {B_RACE_TAPER_DAYS} days before race"
    )


def test_ac3_default_priority_is_a_race():
    """No priority key → defaults to A-race taper length."""
    result_default = taper_recommendation(_state(), RACE_28, 10.0)
    result_a = taper_recommendation(_state(priority="A"), RACE_28, 10.0)
    assert result_default["taper_start_date"] == result_a["taper_start_date"]


def test_ac3_b_race_taper_start_closer_to_race_than_a_race():
    """B-race taper starts closer to race day (shorter window)."""
    result_a = taper_recommendation(_state(priority="A"), RACE_28, 10.0)
    result_b = taper_recommendation(_state(priority="B"), RACE_28, 10.0)
    assert result_b["taper_start_date"] > result_a["taper_start_date"], (
        "B-race mini-taper start should be closer to the race than A-race taper start"
    )


# ── AC4: valid call returns taper_start_date and message ─────────────────────

def test_ac4_a_race_normal_returns_date():
    result = taper_recommendation(_state(), RACE_28, 10.0)
    assert isinstance(result["taper_start_date"], date), (
        "taper_start_date must be a date when achievable"
    )


def test_ac4_a_race_normal_returns_message_string():
    result = taper_recommendation(_state(), RACE_28, 10.0)
    assert isinstance(result["message"], str) and len(result["message"]) > 0


def test_ac4_b_race_normal_returns_date():
    result = taper_recommendation(_state(priority="B"), RACE_28, 10.0)
    assert isinstance(result["taper_start_date"], date)


def test_ac4_b_race_normal_returns_message_string():
    result = taper_recommendation(_state(priority="B"), RACE_28, 10.0)
    assert isinstance(result["message"], str) and len(result["message"]) > 0


# ── AC5: missing / invalid inputs return null + reason ───────────────────────

def test_ac5_null_fitness_state_returns_null_with_reason():
    result = taper_recommendation(None, RACE_28, 10.0)
    assert result["taper_start_date"] is None
    assert result.get("reason"), "reason must be non-empty when fitness_state is None"


def test_ac5_null_race_date_returns_null_with_reason():
    result = taper_recommendation(_state(), None, 10.0)
    assert result["taper_start_date"] is None
    assert result.get("reason"), "reason must be non-empty when race_date is None"


def test_ac5_null_target_form_returns_null_with_reason():
    result = taper_recommendation(_state(), RACE_28, None)
    assert result["taper_start_date"] is None
    assert result.get("reason")


def test_ac5_past_race_date_returns_null_with_reason():
    yesterday = TODAY - timedelta(days=1)
    result = taper_recommendation(_state(), yesterday, 10.0)
    assert result["taper_start_date"] is None
    assert result.get("reason")


def test_ac5_no_exception_for_bad_inputs():
    bad_cases = [
        (None, RACE_28, 10.0),
        (_state(), None, 10.0),
        (_state(), RACE_28, None),
        (_state(), TODAY - timedelta(days=1), 10.0),
    ]
    for args in bad_cases:
        try:
            taper_recommendation(*args)
        except Exception as exc:
            pytest.fail(
                f"taper_recommendation raised {type(exc).__name__} for {args!r}"
            )


# ── AC6: achievable → taper_start = race_date - taper_length constant ────────

def test_ac6_a_race_achievable_taper_start_matches_constant():
    result = taper_recommendation(_state(), RACE_28, 10.0)
    assert result["achievable"] is True
    assert result["taper_start_date"] == RACE_28 - timedelta(days=A_RACE_TAPER_DAYS)


def test_ac6_b_race_achievable_taper_start_matches_constant():
    result = taper_recommendation(_state(priority="B"), RACE_28, 10.0)
    assert result["achievable"] is True
    assert result["taper_start_date"] == RACE_28 - timedelta(days=B_RACE_TAPER_DAYS)


# ── AC7: race too close → taper_start_date is None, honest message ───────────

def test_ac7_too_close_taper_start_date_is_null():
    """When race cannot be reached in positive form, taper_start_date must be None."""
    result = taper_recommendation(_state_high_fatigue(), RACE_3, 10.0)
    assert result["achievable"] is False
    assert result["taper_start_date"] is None, (
        "taper_start_date must be None when the positive form band cannot be reached"
    )


def test_ac7_too_close_message_honest():
    result = taper_recommendation(_state_high_fatigue(), RACE_3, 10.0)
    msg = result["message"].lower()
    assert (
        "too soon" in msg
        or "cannot" in msg
        or "manage" in msg
        or "fatigue" in msg
    ), f"Message must honestly state form cannot be achieved: '{result['message']}'"


def test_ac7_too_close_message_no_false_peak_promise():
    """achievable=False message must not claim a peak will be reached."""
    result = taper_recommendation(_state_high_fatigue(), RACE_3, 10.0)
    msg = result["message"].lower()
    assert not (result["achievable"] is False and "begin easing" in msg and "to peak on" in msg), (
        "achievable=False response must not promise a peak"
    )


def test_ac7_too_close_reason_is_empty():
    """Inputs are valid; achievability is False, not an error — reason must be empty."""
    result = taper_recommendation(_state_high_fatigue(), RACE_3, 10.0)
    assert result.get("reason") == "", "reason should be empty when input is valid but form unreachable"


# ── AC8: delegates form projection to project_form ───────────────────────────

def test_ac8_calls_project_form():
    src = inspect.getsource(taper_recommendation)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    call_names = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.append(node.func.attr)
    assert "project_form" in call_names, (
        "taper_recommendation must delegate projection to project_form"
    )


def test_ac8_no_inline_ewma_math():
    src = inspect.getsource(taper_recommendation)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    ewma_calls = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in {"exp", "_ewma_alpha"}:
                ewma_calls.append(name)
    assert not ewma_calls, (
        f"taper_recommendation reimplements EWMA math ({ewma_calls}); delegate to project_form"
    )


# ── AC9: docstring has two worked examples ────────────────────────────────────

def test_ac9_docstring_exists():
    doc = taper_recommendation.__doc__ or ""
    assert len(doc.strip()) > 0


def test_ac9_docstring_has_a_race_example():
    doc = (taper_recommendation.__doc__ or "").lower()
    assert "a-race" in doc or "a race" in doc or "normal" in doc or "taper" in doc, (
        "docstring must include a normal A-race taper worked example"
    )


def test_ac9_docstring_has_too_close_example():
    doc = (taper_recommendation.__doc__ or "").lower()
    assert "too" in doc or "close" in doc or "false" in doc or "cannot" in doc, (
        "docstring must include a too-close-to-peak worked example"
    )


def test_ac9_docstring_has_at_least_two_example_blocks():
    doc = taper_recommendation.__doc__ or ""
    lower = doc.lower()
    count = lower.count("example") + lower.count("normal") + lower.count("too close")
    assert count >= 2, "docstring must include at least two worked examples"


# ── AC10: no bare numeric literals for thresholds in function body ────────────

def test_ac10_no_bare_threshold_literals_in_body():
    """Constants A_RACE_TAPER_DAYS, B_RACE_TAPER_DAYS, TARGET_FORM_LOWER,
    TARGET_FORM_UPPER must not appear as bare literals in the function body."""
    src = inspect.getsource(taper_recommendation)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    # strip docstring
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    forbidden = {
        float(A_RACE_TAPER_DAYS),
        float(B_RACE_TAPER_DAYS),
        A_RACE_TAPER_DAYS,
        B_RACE_TAPER_DAYS,
        TARGET_FORM_LOWER,
        TARGET_FORM_UPPER,
    }
    bad_literals = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value in forbidden:
                bad_literals.append(node.value)
    assert not bad_literals, (
        f"taper_recommendation body contains bare threshold literals {bad_literals}; "
        "use named constants instead"
    )


# ── AC11: integration — all four scenario types pass ─────────────────────────

def test_ac11_normal_a_race_taper():
    """Normal A-race: 28 days, low fatigue → achievable with A_RACE_TAPER_DAYS start."""
    result = taper_recommendation(_state(priority="A"), RACE_28, 10.0)
    assert result["achievable"] is True
    assert result["taper_start_date"] == RACE_28 - timedelta(days=A_RACE_TAPER_DAYS)
    assert isinstance(result["message"], str) and len(result["message"]) > 0
    assert result["reason"] == ""


def test_ac11_normal_b_race_mini_taper():
    """Normal B-race: 28 days, low fatigue → achievable with B_RACE_TAPER_DAYS start."""
    result = taper_recommendation(_state(priority="B"), RACE_28, 10.0)
    assert result["achievable"] is True
    assert result["taper_start_date"] == RACE_28 - timedelta(days=B_RACE_TAPER_DAYS)
    assert isinstance(result["message"], str) and len(result["message"]) > 0
    assert result["reason"] == ""


def test_ac11_race_too_close_null_start_date():
    """Race too close → achievable=False, taper_start_date=None, honest message."""
    result = taper_recommendation(_state_high_fatigue(), RACE_3, 10.0)
    assert result["achievable"] is False
    assert result["taper_start_date"] is None
    assert isinstance(result["message"], str) and len(result["message"]) > 0
    assert result["reason"] == ""


def test_ac11_missing_fitness_state_returns_null_with_reason():
    result = taper_recommendation(None, RACE_28, 10.0)
    assert result["taper_start_date"] is None
    assert result["achievable"] is None
    assert isinstance(result["reason"], str) and len(result["reason"]) > 0
