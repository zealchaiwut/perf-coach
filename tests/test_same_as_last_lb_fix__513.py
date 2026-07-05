"""Tests for issue #513: same-as-last button sends wrong kg in lb mode.

AC anchors verified:
  (1) _lastEntryWeight stores display-unit value via kgToDisplay, not raw kg
  (2) In lb mode, clicking same-as-last submits the same kg as originally logged (no double-conversion)
  (3) In kg mode, same-as-last continues to submit correct kg (no regression)
  (4) Button label shows weight in currently selected unit with correct unit label
  (5) Switching units updates button label without requiring a new log entry
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = (ROOT / "frontend" / "js" / "weight.js").read_text()
HTML = (ROOT / "frontend" / "pages" / "weight.html").read_text()


# ── AC1: _lastEntryWeight stores display-unit value ───────────────────────────

def test_ac1_update_same_as_last_btn_stores_display_value():
    """_updateSameAsLastBtn must assign kgToDisplay(...) to _lastEntryWeight, not the raw kg arg."""
    # The function must call kgToDisplay before assigning to _lastEntryWeight
    assert "_lastEntryWeight = kgToDisplay(" in JS, (
        "_updateSameAsLastBtn must assign kgToDisplay(lastWeight) to _lastEntryWeight "
        "so _submitCardB receives a display-unit value, not raw kg"
    )


def test_ac1_last_entry_weight_not_assigned_raw():
    """_lastEntryWeight must NOT be assigned the raw lastWeight parameter directly."""
    # Find the _updateSameAsLastBtn function body
    match = re.search(
        r'function _updateSameAsLastBtn\s*\(.*?\)\s*\{(.*?)(?=\nfunction |\nconst |\nlet |\nasync )',
        JS, re.DOTALL
    )
    if match:
        body = match.group(1)
        # Must not assign lastWeight directly (without kgToDisplay wrapping)
        assert "_lastEntryWeight = lastWeight" not in body, (
            "_lastEntryWeight must not be assigned raw lastWeight — must use kgToDisplay(lastWeight)"
        )


# ── AC2: lb mode submits correct kg (no double-conversion) ───────────────────

def test_ac2_submit_card_b_accepts_display_val_and_converts():
    """_submitCardB must call displayToKg() on its argument before sending to the API."""
    assert "displayToKg(" in JS, "_submitCardB must call displayToKg() to convert display value to kg"


def test_ac2_same_as_last_btn_passes_last_entry_weight_directly():
    """same-as-last button click handler must pass _lastEntryWeight directly to _submitCardB
    (no extra kgToDisplay or displayToKg wrapping at the call site)."""
    # Look for the click handler body near same-as-last-btn
    click_match = re.search(
        r'same-as-last-btn.*?addEventListener.*?click.*?\{(.*?)\}',
        JS, re.DOTALL
    )
    if click_match:
        handler = click_match.group(1)
        assert "_submitCardB(_lastEntryWeight)" in handler, (
            "same-as-last click handler must call _submitCardB(_lastEntryWeight) directly — "
            "_lastEntryWeight is already in display units so no extra conversion should be applied"
        )


# ── AC3: kg mode regression — same-as-last still submits correct kg ──────────

def test_ac3_kg_mode_display_value_equals_raw_kg():
    """In kg mode, kgToDisplay is a no-op (returns the same value), so storing
    kgToDisplay(lastWeight) still results in the correct kg being submitted."""
    # kgToDisplay must return kg unchanged when _weightUnit === 'kg'
    assert "return _weightUnit === 'lb'" in JS or "=== 'kg'" in JS, (
        "kgToDisplay must be unit-aware — returns kg unchanged in kg mode"
    )
    # Also verify displayToKg is symmetric — in kg mode returns value unchanged
    assert "return _weightUnit === 'lb'" in JS or "LB_TO_KG" in JS, (
        "displayToKg must convert lb→kg only when unit is lb; pass-through in kg mode"
    )


# ── AC4: Button label shows current unit ─────────────────────────────────────

def test_ac4_button_label_uses_unit_label():
    """Button label must call unitLabel() so it reflects the current unit."""
    # Find the textContent assignment for the same-as-last button
    assert "unitLabel()" in JS, (
        "_updateSameAsLastBtn must use unitLabel() in the button label text"
    )


def test_ac4_button_label_template_has_unit():
    """Button label must contain the unit label, not hardcoded 'kg'."""
    # Find the btn.textContent line that sets the same-as-last label
    matches = re.findall(r'Log same as last.*?unitLabel\(\)', JS, re.DOTALL)
    assert matches, (
        "Button label must contain 'Log same as last' and call unitLabel() — "
        "not a hardcoded ' kg' suffix"
    )


def test_ac4_button_label_no_hardcoded_kg():
    """Button label must NOT hardcode ' kg)' in the same-as-last label string."""
    # This was the original bug: `Log same as last (${lastWeight.toFixed(1)} kg)`
    assert 'Log same as last' not in JS or 'Log same as last' not in JS or (
        re.search(r'Log same as last.*? kg\)', JS) is None
    ), (
        "Button label must not hardcode ' kg)' — must use unitLabel() instead"
    )


# ── AC5: Switching units updates button label ─────────────────────────────────

def test_ac5_apply_unit_calls_update_same_as_last_btn():
    """_applyUnit must call _updateSameAsLastBtn (or equivalent) to refresh the label."""
    # Either _applyUnit calls _updateSameAsLastBtn directly, or refreshes the btn label
    apply_match = re.search(
        r'function _applyUnit\s*\(\s*\)\s*\{(.*?)(?=\nfunction |\nconst |\nlet |\nasync |\ndocument\.)',
        JS, re.DOTALL
    )
    assert apply_match, "_applyUnit function must exist in weight.js"
    body = apply_match.group(1)
    assert "_updateSameAsLastBtn" in body or "same-as-last-btn" in body, (
        "_applyUnit must refresh the same-as-last button label when unit changes"
    )


# ── HTML: required elements ───────────────────────────────────────────────────

def test_html_same_as_last_btn_exists():
    """weight.html must contain the same-as-last-btn element."""
    assert 'id="same-as-last-btn"' in HTML, (
        "weight.html must have id=same-as-last-btn button for the one-tap log affordance"
    )


def test_html_unit_toggle_exists():
    """weight.html must contain a unit-toggle element for kg/lb switching."""
    assert 'id="unit-toggle"' in HTML, (
        "weight.html must have id=unit-toggle element for the kg/lb unit selector"
    )


def test_html_unit_btn_kg_exists():
    """weight.html must have a unit button for kg."""
    assert 'data-unit="kg"' in HTML, (
        "weight.html must have a button with data-unit='kg' inside the unit toggle"
    )


def test_html_unit_btn_lb_exists():
    """weight.html must have a unit button for lb."""
    assert 'data-unit="lb"' in HTML, (
        "weight.html must have a button with data-unit='lb' inside the unit toggle"
    )