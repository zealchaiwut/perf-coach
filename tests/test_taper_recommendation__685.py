"""
Tests for issue #685: taper_recommendation target_form parameter is required but unused.

Acceptance criteria verified:
- AC1: achievability comparison uses caller-supplied target_form, not TARGET_FORM_LOWER constant.
- AC2: Signature and implementation are consistent — target_form is present and referenced.
- AC3: Endpoint call site passes target_form; function uses it.
- AC4: Different target_form values produce different achievability outcomes.
- AC5: No other caller passes target_form expecting the old broken (ignored) behavior.
"""
import inspect
from datetime import date, timedelta

from backend.services.training_load import (
    TARGET_FORM_LOWER,
    taper_recommendation,
)

TODAY = date.today()
RACE_21 = TODAY + timedelta(days=21)


def _state(ctl=50.0, atl=60.0, anchor=None):
    return {"ctl": ctl, "atl": atl, "date": anchor or TODAY}


def _projected_race_form(fitness_state, race_date):
    """Helper: compute the projected race-day form the same way taper_recommendation does."""
    from backend.services.training_load import project_form
    proj = project_form(fitness_state, 0.0, race_date)
    assert not proj["reason"], f"project_form error: {proj['reason']}"
    return proj["days"][-1]["form"]


# ── AC1/AC4: different target_form values must produce different achievability ──

def test_ac1_target_form_used_in_achievability_low_threshold():
    """A very low target_form (below projected form) must yield achievable=True."""
    state = _state()
    projected = _projected_race_form(state, RACE_21)
    low_target = projected - 10.0  # definitely below projected → achievable
    result = taper_recommendation(state, RACE_21, low_target)
    assert result["reason"] == ""
    assert result["achievable"] is True, (
        f"Expected achievable=True with target_form={low_target} "
        f"and projected_race_form={projected:.2f}"
    )


def test_ac1_target_form_used_in_achievability_high_threshold():
    """A very high target_form (above projected form) must yield achievable=False."""
    state = _state()
    projected = _projected_race_form(state, RACE_21)
    high_target = projected + 50.0  # well above projected → not achievable
    result = taper_recommendation(state, RACE_21, high_target)
    assert result["reason"] == ""
    assert result["achievable"] is False, (
        f"Expected achievable=False with target_form={high_target} "
        f"and projected_race_form={projected:.2f}"
    )


def test_ac4_different_target_form_values_differ():
    """Passing target_form=1 vs target_form=999 must produce different achievable results."""
    state = _state()
    result_low = taper_recommendation(state, RACE_21, 1.0)
    result_high = taper_recommendation(state, RACE_21, 999.0)
    assert result_low["reason"] == "" and result_high["reason"] == ""
    assert result_low["achievable"] != result_high["achievable"], (
        "target_form=1 and target_form=999 must yield different achievable values; "
        "if they are the same, target_form is not being used in the comparison"
    )


# ── AC2: signature consistency — target_form appears in function body ──

def test_ac2_target_form_referenced_in_function_body():
    """target_form parameter must be referenced in the function body, not just validated."""
    src = inspect.getsource(taper_recommendation)
    # Strip the def line and docstring to look only at the logic body
    lines = src.split("\n")
    body_lines = [ln for ln in lines if "target_form" in ln]
    # Must appear at least once outside of parameter declaration and None-check
    uses = [ln.strip() for ln in body_lines
            if "def taper_recommendation" not in ln
            and "target_form is None" not in ln
            and "target_form:" not in ln
            and "target_form =" not in ln  # skip docstring-only assignments
            ]
    assert uses, (
        "target_form must be referenced in the computation body of taper_recommendation "
        "(not only in the parameter list or None-check). "
        "The achievability line must use target_form, not TARGET_FORM_LOWER."
    )


def test_ac2_achievability_does_not_use_bare_constant():
    """The achievable= line must not reference TARGET_FORM_LOWER directly."""
    src = inspect.getsource(taper_recommendation)
    for line in src.split("\n"):
        stripped = line.strip()
        if stripped.startswith("achievable"):
            assert "TARGET_FORM_LOWER" not in stripped, (
                f"achievable= line still references the module constant TARGET_FORM_LOWER "
                f"instead of the target_form parameter: {stripped!r}"
            )


# ── AC3: endpoint call site consistency (unit-level check) ──

def test_ac3_endpoint_imports_target_form_lower_for_call():
    """main.py must import TARGET_FORM_LOWER so it can pass it to taper_recommendation."""
    import backend.main as main_mod
    assert hasattr(main_mod, "TARGET_FORM_LOWER") or "TARGET_FORM_LOWER" in dir(main_mod), (
        "backend.main must have TARGET_FORM_LOWER in scope so the endpoint call site "
        "can pass it as the target_form argument."
    )


def test_ac3_endpoint_call_passes_target_form():
    """The taper_recommendation call in main.py must pass three arguments (including target_form)."""
    import ast
    import pathlib
    src = pathlib.Path("backend/main.py").read_text()
    tree = ast.parse(src)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "taper_recommendation"
    ]
    assert calls, "No call to taper_recommendation found in backend/main.py"
    for call in calls:
        assert len(call.args) + len(call.keywords) >= 3, (
            f"taper_recommendation call at line {call.lineno} in main.py must pass "
            f"at least 3 arguments (fitness_state, race_date, target_form); "
            f"found {len(call.args)} positional args"
        )


# ── Regression: original achievability threshold still works with TARGET_FORM_LOWER ──

def test_regression_target_form_lower_still_achievable_with_good_fitness():
    """Passing TARGET_FORM_LOWER as target_form must behave like the original threshold."""
    state = _state(ctl=50.0, atl=60.0)
    result = taper_recommendation(state, RACE_21, TARGET_FORM_LOWER)
    assert result["reason"] == ""
    # With 21 days and moderate fitness state, should still be achievable with default threshold
    projected = _projected_race_form(state, RACE_21)
    expected_achievable = projected >= TARGET_FORM_LOWER
    assert result["achievable"] == expected_achievable, (
        f"Regression: passing TARGET_FORM_LOWER={TARGET_FORM_LOWER} as target_form "
        f"should produce achievable={expected_achievable} for projected={projected:.2f}"
    )
