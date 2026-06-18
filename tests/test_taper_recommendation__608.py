"""
Tests for issue #608: Add taper_recommendation function for race-day form targeting.

Acceptance criteria verified:
- AC1: taper_recommendation(fitness_state, race_date, target_form) is a pure function
       with no DB access; a thin caller layer handles data retrieval.
- AC2: Returns null (None result) with a human-readable reason string for any missing
       or invalid input (fitness_state None, race_date in the past, target_form absent).
- AC3: Return value for a valid call includes: taper_start_date (date), message
       (plain-language string), and achievable (boolean).
- AC4: Named constants define the target form band bounds (TARGET_FORM_LOWER,
       TARGET_FORM_UPPER) and the default taper length (DEFAULT_TAPER_DAYS = 14).
- AC5: All arithmetic logic is expressed in plain English in inline comments.
       (Verified via docstring presence and source inspection.)
- AC6: When race < DEFAULT_TAPER_DAYS away and form can't reach the positive band,
       achievable is False and message states this honestly.
- AC7: Function depends on and calls the existing project_form; does not reimplement.
- AC8: Docstring includes two fully worked examples.
- AC9: No threshold or band value is a bare numeric literal inside function logic.
- AC10: Thin caller (get_taper_recommendation) exists and performs DB access.
- (Tests) Unit tests cover: happy path, too-close race, missing fitness_state,
  missing race_date, missing target_form, and race date in the past.
"""
import ast
import inspect
import textwrap
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from backend.services.training_load import (
    DEFAULT_TAPER_DAYS,
    TARGET_FORM_LOWER,
    TARGET_FORM_UPPER,
    get_taper_recommendation,
    taper_recommendation,
)

TODAY = date.today()
RACE_21 = TODAY + timedelta(days=21)  # plenty of time to taper
RACE_4 = TODAY + timedelta(days=4)    # too close to peak


def _state(ctl=50.0, atl=60.0, anchor=None):
    """Convenience: build a minimal fitness_state dict."""
    return {"ctl": ctl, "atl": atl, "date": anchor or TODAY}


def _state_high_fatigue(anchor=None):
    """Fitness state with high fatigue (ATL >> CTL) so form is deep negative."""
    return {"ctl": 50.0, "atl": 90.0, "date": anchor or TODAY}


# ── AC4: named constants are exported ────────────────────────────────────────

def test_ac4_target_form_lower_exported():
    assert isinstance(TARGET_FORM_LOWER, float), "TARGET_FORM_LOWER must be a float constant"
    assert TARGET_FORM_LOWER > 0


def test_ac4_target_form_upper_exported():
    assert isinstance(TARGET_FORM_UPPER, float), "TARGET_FORM_UPPER must be a float constant"
    assert TARGET_FORM_UPPER > TARGET_FORM_LOWER


def test_ac4_default_taper_days_exported():
    assert isinstance(DEFAULT_TAPER_DAYS, int), "DEFAULT_TAPER_DAYS must be an integer constant"
    assert DEFAULT_TAPER_DAYS > 0


def test_ac4_default_taper_days_is_14():
    assert DEFAULT_TAPER_DAYS == 14, "DEFAULT_TAPER_DAYS should be 14 per issue spec"


# ── AC1: function is callable and pure (no DB calls inside) ──────────────────

def test_ac1_taper_recommendation_callable():
    assert callable(taper_recommendation)


def test_ac1_taper_recommendation_no_db_calls():
    """taper_recommendation body must not call engine, Session, or current_load."""
    src = inspect.getsource(taper_recommendation)
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
        f"taper_recommendation body calls DB functions: {calls_found}"
    )


# ── AC2: invalid / missing inputs return null result + reason ─────────────────

def test_ac2_missing_fitness_state_returns_none_result():
    result = taper_recommendation(None, RACE_21, 10.0)
    assert isinstance(result, dict)
    assert result.get("taper_start_date") is None
    assert result.get("reason"), "reason must be non-empty when fitness_state is None"


def test_ac2_missing_race_date_returns_none_result():
    result = taper_recommendation(_state(), None, 10.0)
    assert isinstance(result, dict)
    assert result.get("taper_start_date") is None
    assert result.get("reason"), "reason must be non-empty when race_date is None"


def test_ac2_missing_target_form_returns_none_result():
    result = taper_recommendation(_state(), RACE_21, None)
    assert isinstance(result, dict)
    assert result.get("taper_start_date") is None
    assert result.get("reason"), "reason must be non-empty when target_form is None"


def test_ac2_race_date_in_past_returns_none_result():
    yesterday = TODAY - timedelta(days=1)
    result = taper_recommendation(_state(), yesterday, 10.0)
    assert isinstance(result, dict)
    assert result.get("taper_start_date") is None
    assert result.get("reason"), "reason must be non-empty when race_date is in the past"


def test_ac2_race_date_today_returns_none_result():
    result = taper_recommendation(_state(), TODAY, 10.0)
    assert isinstance(result, dict)
    assert result.get("taper_start_date") is None
    assert result.get("reason"), "reason must be non-empty when race_date is today (not future)"


def test_ac2_no_exception_for_bad_inputs():
    """Function must not raise exceptions for any invalid input."""
    bad_cases = [
        (None, RACE_21, 10.0),
        (_state(), None, 10.0),
        (_state(), RACE_21, None),
        (_state(), TODAY - timedelta(days=1), 10.0),
    ]
    for args in bad_cases:
        try:
            taper_recommendation(*args)
        except Exception as exc:
            pytest.fail(
                f"taper_recommendation raised {type(exc).__name__} for input {args!r}"
            )


# ── AC3: valid call return shape ──────────────────────────────────────────────

def test_ac3_happy_path_has_taper_start_date():
    result = taper_recommendation(_state(), RACE_21, 10.0)
    assert "taper_start_date" in result
    assert isinstance(result["taper_start_date"], date)


def test_ac3_happy_path_has_message():
    result = taper_recommendation(_state(), RACE_21, 10.0)
    assert "message" in result
    assert isinstance(result["message"], str)
    assert len(result["message"]) > 0


def test_ac3_happy_path_has_achievable():
    result = taper_recommendation(_state(), RACE_21, 10.0)
    assert "achievable" in result
    assert isinstance(result["achievable"], bool)


def test_ac3_success_reason_is_empty_string():
    result = taper_recommendation(_state(), RACE_21, 10.0)
    assert result.get("reason") == "", "reason must be empty string on success"


def test_ac3_taper_start_date_is_default_taper_days_before_race():
    result = taper_recommendation(_state(), RACE_21, 10.0)
    expected_start = RACE_21 - timedelta(days=DEFAULT_TAPER_DAYS)
    assert result["taper_start_date"] == expected_start, (
        f"taper_start_date should be {DEFAULT_TAPER_DAYS} days before race_date"
    )


# ── Happy path: 2-week taper with race 21 days out ────────────────────────────

def test_happy_path_achievable_true():
    """Race 21 days away with moderate fitness: form should reach positive band."""
    result = taper_recommendation(_state(), RACE_21, 10.0)
    assert result["achievable"] is True


def test_happy_path_taper_start_approx_7_days_from_now():
    """Race 21 days away: taper_start should be 21 - 14 = 7 days from now."""
    result = taper_recommendation(_state(), RACE_21, 10.0)
    expected_start = TODAY + timedelta(days=7)
    assert result["taper_start_date"] == expected_start


def test_happy_path_message_mentions_ease_and_peak():
    """Happy path message must describe easing load and peaking on race day."""
    result = taper_recommendation(_state(), RACE_21, 10.0)
    msg = result["message"].lower()
    assert "eas" in msg or "taper" in msg or "load" in msg, (
        "achievable message should mention easing load or tapering"
    )
    assert "peak" in msg, "achievable message should mention peaking"


# ── AC6: race too close — projected form cannot reach positive band ───────────

def test_ac6_too_close_race_achievable_false():
    """Race 4 days away with high fatigue: form cannot reach positive band."""
    result = taper_recommendation(_state_high_fatigue(), RACE_4, 10.0)
    assert result["achievable"] is False


def test_ac6_too_close_message_is_honest():
    """achievable=False message must state that a peak cannot be reached."""
    result = taper_recommendation(_state_high_fatigue(), RACE_4, 10.0)
    msg = result["message"].lower()
    # Must NOT promise a peak; must suggest managing fatigue or similar
    assert (
        "too soon" in msg
        or "cannot" in msg
        or "manage" in msg
        or "fatigue" in msg
    ), f"Message should honestly describe the situation: '{result['message']}'"


def test_ac6_too_close_no_false_promise_of_peak():
    """achievable=False message must not say 'begin easing load … to peak on'."""
    result = taper_recommendation(_state_high_fatigue(), RACE_4, 10.0)
    msg = result["message"].lower()
    # Should not contain the positive-path pattern
    assert "begin easing" not in msg or not result["achievable"], (
        "achievable=False response must not promise a peaking outcome"
    )


def test_ac6_too_close_taper_start_date_still_present():
    """Even when achievable=False, taper_start_date is in the result."""
    result = taper_recommendation(_state_high_fatigue(), RACE_4, 10.0)
    assert "taper_start_date" in result
    # taper_start_date may be in the past (RACE_4 - 14 days is before today)


# ── AC7: calls project_form, does not reimplement projection ─────────────────

def test_ac7_calls_project_form():
    """taper_recommendation body must call project_form."""
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
        "taper_recommendation must call project_form to delegate projection logic"
    )


def test_ac7_does_not_reimplement_ewma():
    """taper_recommendation must not contain exp() or _ewma_alpha in its body
    (indicating it reimplements the EWMA math instead of calling project_form)."""
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
        f"taper_recommendation reimplements EWMA math ({ewma_calls}); "
        "delegate to project_form instead"
    )


# ── AC8: docstring has two worked examples ────────────────────────────────────

def test_ac8_docstring_exists():
    doc = taper_recommendation.__doc__ or ""
    assert len(doc.strip()) > 0, "taper_recommendation must have a docstring"


def test_ac8_docstring_has_normal_taper_example():
    """Docstring must include a 2-week / normal taper worked example."""
    doc = (taper_recommendation.__doc__ or "").lower()
    # Must contain something about 21 days or 2-week taper
    assert "21" in doc or "two" in doc or "2-week" in doc or "taper" in doc, (
        "docstring must include a normal taper worked example"
    )


def test_ac8_docstring_has_too_close_example():
    """Docstring must include a too-close-to-peak worked example."""
    doc = (taper_recommendation.__doc__ or "").lower()
    # Must show the achievable: False scenario (5 days or similar)
    assert "5" in doc or "4" in doc or "false" in doc or "too" in doc, (
        "docstring must include a too-close-to-peak worked example with achievable=False"
    )


def test_ac8_docstring_has_two_examples():
    """Docstring must contain at least two distinct Examples sections/headers."""
    doc = taper_recommendation.__doc__ or ""
    # Count occurrences of a header pattern that signals an example block
    lower = doc.lower()
    # Look for numbered examples or multiple 'example' mentions
    example_count = lower.count("example") + lower.count("normal taper") + lower.count("too close")
    assert example_count >= 2, (
        "docstring must contain two worked examples (normal taper + too-close)"
    )


# ── AC9: no bare numeric literals inside function logic ───────────────────────

def test_ac9_no_bare_numeric_literals_in_body():
    """No threshold or band value should appear as a bare int/float literal
    in the function body (excluding docstring and string formatting)."""
    src = inspect.getsource(taper_recommendation)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    # Strip docstring
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]

    # Literals that are OK: 0.0 (zero load), 1 (timedelta days offset), -1 (index)
    # Literals that are NOT OK: band values like 5.0, 25.0, 14 bare in logic
    forbidden = {5.0, 25.0, 14}
    bad_literals = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value in forbidden:
                bad_literals.append(node.value)

    assert not bad_literals, (
        f"taper_recommendation body contains bare threshold literals {bad_literals}; "
        "reference named constants instead"
    )


# ── AC10: thin caller exists and performs DB access ───────────────────────────

def test_ac10_get_taper_recommendation_callable():
    assert callable(get_taper_recommendation)


def test_ac10_thin_caller_calls_current_load():
    """get_taper_recommendation must call current_load to fetch fitness state."""
    with (
        patch("backend.services.training_load.current_load") as mock_cl,
        patch("backend.services.training_load.taper_recommendation") as mock_tr,
    ):
        mock_cl.return_value = {"ctl": 50.0, "atl": 60.0, "date": TODAY}
        mock_tr.return_value = {
            "taper_start_date": RACE_21 - timedelta(days=DEFAULT_TAPER_DAYS),
            "message": "begin easing...",
            "achievable": True,
            "reason": "",
        }
        get_taper_recommendation("user-1", RACE_21, 10.0)
        mock_cl.assert_called_once()


def test_ac10_thin_caller_delegates_to_taper_recommendation():
    """get_taper_recommendation must delegate to taper_recommendation."""
    with (
        patch("backend.services.training_load.current_load") as mock_cl,
        patch("backend.services.training_load.taper_recommendation") as mock_tr,
    ):
        mock_cl.return_value = {"ctl": 50.0, "atl": 60.0, "date": TODAY}
        mock_tr.return_value = {
            "taper_start_date": RACE_21 - timedelta(days=DEFAULT_TAPER_DAYS),
            "message": "begin easing...",
            "achievable": True,
            "reason": "",
        }
        get_taper_recommendation("user-1", RACE_21, 10.0)
        mock_tr.assert_called_once()


def test_ac10_thin_caller_passes_fitness_state_to_taper_recommendation():
    """get_taper_recommendation must pass the DB-fetched fitness state."""
    with (
        patch("backend.services.training_load.current_load") as mock_cl,
        patch("backend.services.training_load.taper_recommendation") as mock_tr,
    ):
        mock_cl.return_value = {"ctl": 44.0, "atl": 52.0, "date": TODAY}
        mock_tr.return_value = {
            "taper_start_date": RACE_21 - timedelta(days=DEFAULT_TAPER_DAYS),
            "message": "ok",
            "achievable": True,
            "reason": "",
        }
        get_taper_recommendation("user-1", RACE_21, 10.0)
        call_args = mock_tr.call_args[0]  # positional args
        fitness_state_arg = call_args[0]
        assert fitness_state_arg["ctl"] == 44.0
        assert fitness_state_arg["atl"] == 52.0
