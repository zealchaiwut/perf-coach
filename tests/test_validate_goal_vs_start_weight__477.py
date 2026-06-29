"""Tests for issue #477: Validate goal vs start weight before saving target.

AC anchors verified:
  (ac1) _saveEditPanel in weight.js reads start_weight from _activeTarget for
        existing targets (start weight is fixed, not editable)
  (ac2) if existing target is loss-direction (start > original_goal) and new
        goalW >= start_weight, an error is surfaced inline ("Goal must be less
        than start weight") and the save is aborted
  (ac3) the guard also handles new-target flow: if goalW equals the current
        weight (startW from chart stats), the same direction error fires
  (ac4) the validation fires BEFORE the fetch call so no network request is made
        for invalid input
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS_PATH = ROOT / "frontend" / "js" / "weight.js"
JS_SRC = JS_PATH.read_text() if JS_PATH.exists() else ""


def _save_panel_body() -> str:
    """Extract the body of _saveEditPanel from weight.js."""
    m = re.search(
        r"async function _saveEditPanel\(\)\s*\{(.+?)^\}",
        JS_SRC,
        re.DOTALL | re.MULTILINE,
    )
    return m.group(1) if m else ""


# ── AC1: start weight source ──────────────────────────────────────────────────

def test_ac1_save_reads_activeTarget_start_weight():
    """_saveEditPanel must reference _activeTarget.start_weight_kg to obtain
    the fixed start weight for the validation check."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    assert "start_weight_kg" in body, (
        "_saveEditPanel must read _activeTarget.start_weight_kg for the goal-vs-start check"
    )


# ── AC2: loss-direction guard ─────────────────────────────────────────────────

def test_ac2_error_message_goal_less_than_start():
    """The exact error string 'Goal must be less than start weight' must appear
    inside _saveEditPanel so the user sees it inline before any fetch is made."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    assert "Goal must be less than start weight" in body, (
        "_saveEditPanel must set errEl.textContent = 'Goal must be less than start weight' "
        "when loss-direction target has goalW >= startW"
    )


def test_ac2_guard_returns_early():
    """After setting the error text the function must return without fetching,
    i.e. 'return' appears after the error-message assignment inside the guard."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    # Find the segment around the error message
    idx = body.find("Goal must be less than start weight")
    assert idx != -1, "Error message not found in _saveEditPanel"
    # 'return' must appear shortly after (within next 200 chars)
    snippet = body[idx : idx + 200]
    assert "return" in snippet, (
        "A 'return' statement must follow the 'Goal must be less than start weight' "
        "error assignment to abort the save"
    )


# ── AC3: equal-weight guard (no-direction case) ───────────────────────────────

def test_ac3_guard_triggers_on_goal_equal_to_start():
    """The comparison operator used for the guard must be >= (greater-than-or-equal)
    so it fires when goalW == startW as well as goalW > startW."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    # The guard expression must use >=
    assert ">=" in body, (
        "_saveEditPanel must use '>=' in the start-weight guard so goalW == startW "
        "is also blocked (a target with identical start and goal has no direction)"
    )


# ── AC4: guard fires before fetch ────────────────────────────────────────────

def test_ac4_validation_before_fetch():
    """The start-weight guard must appear in the source before the fetch() call
    so no network request is made for invalid input."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"

    idx_guard = body.find("Goal must be less than start weight")
    idx_fetch = body.find("fetch(")

    assert idx_guard != -1, "Guard error message not found"
    assert idx_fetch != -1, "fetch() call not found in _saveEditPanel"
    assert idx_guard < idx_fetch, (
        "The goal-vs-start guard must appear before the first fetch() call "
        "inside _saveEditPanel"
    )
