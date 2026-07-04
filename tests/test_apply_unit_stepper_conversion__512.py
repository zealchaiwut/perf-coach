"""
TDD tests for issue #512 – _applyUnit() does not convert stepper displayed value on unit switch.

Each test anchors exactly one AC item from the issue.
Tests parse static source files only — no live server needed.
"""

import re
from pathlib import Path

WEIGHT_JS   = Path(__file__).parent.parent / "frontend" / "js" / "weight.js"
WEIGHT_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "weight.html"

js   = WEIGHT_JS.read_text()
html = WEIGHT_HTML.read_text()


# ── AC1 & AC2: stepper value reconverted on unit switch ──────────────────────

def test_apply_unit_retrieves_logged_strip_weight():
    """AC1/AC2/AC5: _applyUnit() reads logged-strip.dataset.weight to get stored kg."""
    # Must access logged-strip's dataset.weight inside _applyUnit
    apply_unit_block = re.search(
        r"function _applyUnit\(\)\s*\{(.+?)(?=\nfunction |\Z)",
        js, re.DOTALL
    )
    assert apply_unit_block, "_applyUnit() function must exist in weight.js"
    body = apply_unit_block.group(1)
    assert "logged-strip" in body, \
        "_applyUnit() must read from logged-strip element to get stored kg value"
    assert "dataset.weight" in body, \
        "_applyUnit() must access dataset.weight to retrieve stored kg value"


def test_apply_unit_calls_prefill_stepper():
    """AC5: _applyUnit() calls _prefillStepper after updating bounds."""
    apply_unit_block = re.search(
        r"function _applyUnit\(\)\s*\{(.+?)(?=\nfunction |\Z)",
        js, re.DOTALL
    )
    assert apply_unit_block, "_applyUnit() function must exist in weight.js"
    body = apply_unit_block.group(1)
    assert "_prefillStepper(" in body, \
        "_applyUnit() must call _prefillStepper() after updating stepper min/max/step"


# ── AC3: submit button label reflects converted value ────────────────────────

def test_update_log_btn_label_uses_unit_label():
    """AC3: _updateLogBtnLabel uses unitLabel() not hardcoded 'kg'."""
    update_label_block = re.search(
        r"function _updateLogBtnLabel\(\)\s*\{(.+?)(?=\nfunction |\Z)",
        js, re.DOTALL
    )
    assert update_label_block, "_updateLogBtnLabel() must exist in weight.js"
    body = update_label_block.group(1)
    assert "unitLabel()" in body, \
        "_updateLogBtnLabel() must use unitLabel() so label shows 'lb' or 'kg' dynamically"
    assert "hardcoded 'kg'" not in body  # just documentation check
    # Must NOT hardcode literal ' kg' in the log button text assignment
    # (the string can have kg only inside unitLabel() call context)
    hardcoded = re.search(r'textContent\s*=.*"Log.*\s+kg"', body)
    assert not hardcoded, \
        "_updateLogBtnLabel() must not hardcode ' kg' — use unitLabel() instead"


# ── AC4: submitting after unit switch stores correct kg ──────────────────────

def test_submit_card_b_converts_display_to_kg():
    """AC4: _submitCardB() calls displayToKg() so stored value is always canonical kg."""
    submit_block = re.search(
        r"async function _submitCardB\((.+?)(?=\nasync function |\nfunction |\Z)",
        js, re.DOTALL
    )
    assert submit_block, "_submitCardB() must exist in weight.js"
    body = submit_block.group(0)
    assert "displayToKg(" in body, \
        "_submitCardB() must call displayToKg() to convert display value before storing"


# ── AC5: _prefillStepper accepts kg and converts to display units ─────────────

def test_prefill_stepper_converts_kg_to_display():
    """AC5: _prefillStepper() uses kgToDisplay() to set correct display value."""
    prefill_block = re.search(
        r"function _prefillStepper\((.+?)(?=\nfunction |\Z)",
        js, re.DOTALL
    )
    assert prefill_block, "_prefillStepper() must exist in weight.js"
    body = prefill_block.group(0)
    assert "kgToDisplay(" in body, \
        "_prefillStepper() must use kgToDisplay() to convert kg to the current display unit"


# ── AC6: no error on fresh state (no prior weight loaded) ────────────────────

def test_apply_unit_guards_against_missing_weight():
    """AC6: _applyUnit() guards against NaN/null dataset.weight — no unconditional throw path."""
    apply_unit_block = re.search(
        r"function _applyUnit\(\)\s*\{(.+?)(?=\nfunction |\Z)",
        js, re.DOTALL
    )
    assert apply_unit_block, "_applyUnit() function must exist in weight.js"
    body = apply_unit_block.group(1)
    # Must have a conditional check (isNaN or != null) before calling _prefillStepper
    has_guard = re.search(r"isNaN\s*\(|!=\s*null|!==\s*null|\?\s*parseFloat", body)
    assert has_guard, \
        "_applyUnit() must guard against NaN/null stored weight before calling _prefillStepper"


# ── Unit system presence ──────────────────────────────────────────────────────

def test_unit_system_functions_present():
    """Unit system helpers must exist: kgToDisplay, displayToKg, unitLabel, displayMin, displayMax."""
    for fn in ("kgToDisplay", "displayToKg", "unitLabel", "displayMin", "displayMax"):
        assert f"function {fn}(" in js, f"{fn}() must be defined in weight.js"


def test_weight_unit_state_variable():
    """_weightUnit state variable must exist and default to 'kg'."""
    assert "_weightUnit" in js, "_weightUnit must be declared in weight.js"
    assert "'kg'" in js or '"kg"' in js, "_weightUnit must default to 'kg'"


def test_init_unit_toggle_function_present():
    """_initUnitToggle() must exist to wire up the kg/lb toggle buttons."""
    assert "function _initUnitToggle(" in js, \
        "_initUnitToggle() must exist to set up unit toggle event listeners"


# ── HTML: unit toggle element must be present ─────────────────────────────────

def test_html_has_unit_toggle_element():
    """weight.html must contain a unit-toggle element with kg and lb buttons."""
    assert 'id="unit-toggle"' in html, \
        "weight.html must have a unit-toggle element (id='unit-toggle')"
    assert 'data-unit="kg"' in html, \
        "weight.html must have a kg unit button (data-unit='kg')"
    assert 'data-unit="lb"' in html, \
        "weight.html must have an lb unit button (data-unit='lb')"


# ── Clamp bounds are unit-aware ───────────────────────────────────────────────

def test_clamp_stepper_uses_display_bounds():
    """_clampStepperValue() must use displayMin()/displayMax() not hardcoded 20/300."""
    clamp_block = re.search(
        r"function _clampStepperValue\((.+?)(?=\nfunction |\Z)",
        js, re.DOTALL
    )
    assert clamp_block, "_clampStepperValue() must exist in weight.js"
    body = clamp_block.group(0)
    assert "displayMin()" in body, \
        "_clampStepperValue() must use displayMin() not hardcoded 20"
    assert "displayMax()" in body, \
        "_clampStepperValue() must use displayMax() not hardcoded 300"
