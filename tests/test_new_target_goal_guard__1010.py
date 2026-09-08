"""Tests for issue #1010: new-target path in _saveEditPanel must guard goalW >= startW.

AC anchors verified:
  (ac1) For new-target flow (_activeTarget is null), the start weight comes from
        _chartData.stats.current_weight_kg — not a hard-coded fallback.
  (ac2) The isLossTarget ternary's new-target branch (the falsy path when
        _activeTarget is null) resolves to a truthy value so the
        goalW >= startWVal guard CAN fire — i.e. the branch is not ': false'.
  (ac3) The guard block (isLossTarget && goalW >= startWVal) fires when the
        new-target branch is active: isLossTarget is truthy AND the '>='
        operator is used, so goalW equal to startWVal is also blocked.
  (ac4) The startWVal assignment references _chartData.stats.current_weight_kg
        in the new-target (null _activeTarget) branch — not some other field.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS_PATH = ROOT / "frontend" / "js" / "weight.js"
JS_SRC = JS_PATH.read_text() if JS_PATH.exists() else ""


def _save_panel_body() -> str:
    m = re.search(
        r"async function _saveEditPanel\(\)\s*\{(.+?)^\}",
        JS_SRC,
        re.DOTALL | re.MULTILINE,
    )
    return m.group(1) if m else ""


# ── AC1: new-target startWVal uses chart stats ────────────────────────────────

def test_ac1_startWVal_uses_chart_current_weight_for_new_target():
    """When _activeTarget is null, startWVal must come from
    _chartData.stats.current_weight_kg (the chart's live current weight)."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    # The startWVal assignment must reference _chartData.stats and current_weight_kg
    assert "_chartData" in body and "current_weight_kg" in body, (
        "_saveEditPanel must use _chartData.stats.current_weight_kg as startWVal "
        "for the new-target path"
    )
    # The two must appear together in the startWVal ternary
    m = re.search(r'const startWVal\s*=[^;]+;', body, re.DOTALL)
    assert m, "startWVal assignment not found in _saveEditPanel"
    startw_decl = m.group(0)
    assert "current_weight_kg" in startw_decl, (
        "startWVal must reference current_weight_kg for the new-target branch"
    )
    assert "_chartData" in startw_decl, (
        "startWVal must reference _chartData for the new-target branch"
    )


# ── AC2: isLossTarget new-target branch is NOT false ─────────────────────────

def test_ac2_isLossTarget_new_target_branch_not_false():
    """The isLossTarget ternary's falsy branch (new-target path) must not be
    the literal 'false', so the guard can fire when goalW >= startWVal."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    m = re.search(r'const isLossTarget\s*=([^;]+);', body, re.DOTALL)
    assert m, "isLossTarget assignment not found in _saveEditPanel"
    decl = m.group(1)
    # Falsy branch is after the last ':'
    assert ': false' not in decl and ':false' not in decl, (
        "isLossTarget new-target branch must not be hard-coded to 'false'; "
        "this prevents the guard from ever firing during new-target creation"
    )


def test_ac2_isLossTarget_new_target_branch_is_truthy():
    """The isLossTarget ternary's falsy branch must resolve to a truthy value
    (e.g. 'true') so the goalW >= startWVal guard fires for new targets."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    m = re.search(r'const isLossTarget\s*=([^;]+);', body, re.DOTALL)
    assert m, "isLossTarget assignment not found in _saveEditPanel"
    decl = m.group(1)
    # The falsy branch (after the last colon) must be 'true'
    # Split on ':' and check the last segment is truthy
    parts = decl.split(':')
    falsy_branch = parts[-1].strip().rstrip(';').strip()
    assert falsy_branch == 'true', (
        f"isLossTarget new-target branch must be 'true' to enable the guard "
        f"when _activeTarget is null; got: '{falsy_branch}'"
    )


# ── AC3: combined guard fires for new-target when goalW >= startWVal ──────────

def test_ac3_guard_uses_gte_operator():
    """The goal-vs-start guard must use >= so goalW equal to startWVal is also
    blocked — a new target with goal == current weight has no direction."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    # isLossTarget && goalW >= startWVal pattern
    assert "goalW >= startWVal" in body or ">= startWVal" in body, (
        "_saveEditPanel must use '>= startWVal' so equal-weight case is blocked"
    )


def test_ac3_guard_structure_can_fire_for_new_target():
    """Verify that the guard block — 'if (isLossTarget && goalW >= startWVal)' —
    appears in _saveEditPanel and that, with isLossTarget=true (new-target path),
    the condition reduces to 'goalW >= startWVal', blocking equal or higher goals."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    # The full guard must be present
    assert "isLossTarget && goalW >= startWVal" in body, (
        "_saveEditPanel must contain 'if (isLossTarget && goalW >= startWVal)' "
        "as the goal-vs-start guard"
    )
    # Error message must be inside the guard block
    idx_guard = body.find("isLossTarget && goalW >= startWVal")
    idx_error = body.find("Goal must be less than start weight", idx_guard)
    assert idx_error != -1 and idx_error < idx_guard + 200, (
        "The error message 'Goal must be less than start weight' must appear "
        "immediately inside the goal-vs-start guard block"
    )


# ── AC4: new-target startWVal is null-guarded ─────────────────────────────────

def test_ac4_startWVal_null_guarded_for_new_target():
    """When _chartData or _chartData.stats is unavailable, startWVal must be
    null (not crash), and the null check 'if (startWVal != null)' must gate
    the guard so it only fires when chart data is present."""
    body = _save_panel_body()
    assert body, "_saveEditPanel not found in weight.js"
    # startWVal assignment must have a null fallback for missing chart data
    m = re.search(r'const startWVal\s*=([^;]+);', body, re.DOTALL)
    assert m, "startWVal assignment not found"
    decl = m.group(0)
    assert "null" in decl, (
        "startWVal must fall back to null when _chartData is unavailable "
        "(prevents the guard firing when chart hasn't loaded yet)"
    )
    # The guard must be wrapped in 'if (startWVal != null)'
    assert "startWVal != null" in body, (
        "_saveEditPanel must gate the loss-direction guard with "
        "'if (startWVal != null)'"
    )
