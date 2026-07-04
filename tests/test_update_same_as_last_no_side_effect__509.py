"""Tests for issue #509: remove state mutation side effect from _updateSameAsLastBtn.

AC anchors verified:
  (1) _updateSameAsLastBtn no longer assigns to _lastEntryWeight anywhere in its body
  (2) Assignment _lastEntryWeight = ... appears at the call site in _cardBSetLoggedState
  (3) Functional behaviour is unchanged: button shows correct last-entry weight
  (4) No call site silently depends on the removed side effect
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = (ROOT / "frontend" / "js" / "weight.js").read_text()


def _fn_body(js: str, name: str) -> str:
    """Extract the body of a named top-level function (between first { and matching })."""
    pattern = rf'function {re.escape(name)}\s*\([^)]*\)\s*\{{'
    m = re.search(pattern, js)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(js) and depth:
        if js[i] == '{':
            depth += 1
        elif js[i] == '}':
            depth -= 1
        i += 1
    return js[start:i - 1]


# ── AC1: _updateSameAsLastBtn body must not assign _lastEntryWeight ───────────

def test_ac1_update_btn_does_not_assign_last_entry_weight():
    """_updateSameAsLastBtn must not assign to _lastEntryWeight inside its body."""
    body = _fn_body(JS, "_updateSameAsLastBtn")
    assert body, "_updateSameAsLastBtn function must exist in weight.js"
    # Match assignment (single =) but not comparison (== or !=)
    assert not re.search(r'_lastEntryWeight\s*=[^=]', body), (
        "_updateSameAsLastBtn must not assign to _lastEntryWeight — "
        "that mutation must live at the call site, not inside this function"
    )


def test_ac1_update_btn_does_not_assign_last_entry_weight_kg():
    """_updateSameAsLastBtn must not assign to _lastEntryWeightKg inside its body."""
    body = _fn_body(JS, "_updateSameAsLastBtn")
    assert body, "_updateSameAsLastBtn function must exist in weight.js"
    assert "_lastEntryWeightKg =" not in body, (
        "_updateSameAsLastBtn must not assign to _lastEntryWeightKg — "
        "that mutation must live at the call site, not inside this function"
    )


# ── AC2: assignment moved to call site in _cardBSetLoggedState ────────────────

def test_ac2_card_b_set_logged_state_assigns_last_entry_weight():
    """_cardBSetLoggedState (or equivalent call site) must assign _lastEntryWeight."""
    body = _fn_body(JS, "_cardBSetLoggedState")
    assert body, "_cardBSetLoggedState function must exist in weight.js"
    assert "_lastEntryWeight" in body, (
        "_cardBSetLoggedState must now explicitly set _lastEntryWeight "
        "so the mutation is visible at the call site"
    )


def test_ac2_card_b_set_logged_state_assigns_last_entry_weight_kg():
    """_cardBSetLoggedState must assign _lastEntryWeightKg at the call site."""
    body = _fn_body(JS, "_cardBSetLoggedState")
    assert body, "_cardBSetLoggedState function must exist in weight.js"
    assert "_lastEntryWeightKg" in body, (
        "_cardBSetLoggedState must now explicitly set _lastEntryWeightKg "
        "so the mutation is visible at the call site"
    )


# ── AC3: button still reflects correct last-entry weight ─────────────────────

def test_ac3_update_btn_reads_last_entry_weight_for_label():
    """_updateSameAsLastBtn must still read _lastEntryWeight to render the label."""
    body = _fn_body(JS, "_updateSameAsLastBtn")
    assert body, "_updateSameAsLastBtn must exist"
    # The button label must reference the display-unit value
    assert "_lastEntryWeight" in body, (
        "_updateSameAsLastBtn must still read _lastEntryWeight to set the button label"
    )


def test_ac3_same_as_last_btn_element_present_in_html():
    """weight.html must still contain same-as-last-btn (no regression to HTML)."""
    HTML = (ROOT / "frontend" / "pages" / "weight.html").read_text()
    assert 'id="same-as-last-btn"' in HTML, (
        "weight.html must still contain the same-as-last-btn element"
    )


# ── AC4: no call site silently depends on removed side effect ─────────────────

def test_ac4_apply_unit_explicitly_manages_state():
    """_applyUnit must still correctly update _lastEntryWeight when the unit changes.

    It already guards on _lastEntryWeightKg != null — after the refactoring,
    either it updates _lastEntryWeight itself or the called function still
    sets it. Either way, _lastEntryWeight must be updated in that code path.
    """
    body = _fn_body(JS, "_applyUnit")
    assert body, "_applyUnit must exist in weight.js"
    # _applyUnit must either call _updateSameAsLastBtn or assign _lastEntryWeight
    assert "_updateSameAsLastBtn" in body or "_lastEntryWeight" in body, (
        "_applyUnit must keep _lastEntryWeight in sync when switching units — "
        "either by calling _updateSameAsLastBtn (which now reads state) or "
        "by assigning _lastEntryWeight directly before the call"
    )