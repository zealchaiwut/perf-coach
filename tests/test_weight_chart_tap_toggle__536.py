"""
TDD tests for issue #536 — Weight chart tap-to-show: touchend hides tooltip immediately.

6 AC anchors:
  (ac1) Tapping inactive dot shows tooltip and it persists after touchend
  (ac2) Tapping the currently-active dot hides the tooltip (tap-to-dismiss)
  (ac3) Tapping a different dot while tooltip is visible switches to the new point
  (ac4) touchend no longer unconditionally hides the tooltip
  (ac5) Persistent labels for today's data point (AC1–4 of #515) are unaffected
  (ac6) Desktop mouseover/mouseout behavior is unchanged
"""
from pathlib import Path

CHART_JS = Path(__file__).parent.parent / "frontend" / "js" / "weight-chart.js"


def _src():
    return CHART_JS.read_text()


# ── AC1: Tapping inactive dot shows and persists tooltip ─────────────────────

def test_ac1_touchstart_shows_tooltip():
    """AC1: touchstart handler still calls _showTooltip for a tapped point."""
    src = _src()
    ts_pos = src.find("touchstart")
    assert ts_pos != -1, "touchstart listener missing from weight-chart.js"
    near = src[ts_pos : ts_pos + 500]
    assert "_showTooltip" in near or "_findNearestDot" in near, (
        "touchstart handler must call _showTooltip/_findNearestDot to display tooltip on tap"
    )


def test_ac1_tooltip_persists_after_touchend():
    """AC1: touchend does NOT unconditionally call _hideTooltip (tooltip persists after lift)."""
    src = _src()
    # Find the touchend listener block
    te_pos = src.find('"touchend"')
    if te_pos == -1:
        te_pos = src.find("'touchend'")
    if te_pos == -1:
        # touchend may have been removed entirely — that satisfies AC4/AC1
        assert "touchend" not in src, (
            "touchend found in source but not as a quoted event string — check registration"
        )
        return
    # If touchend is still present, its handler must NOT unconditionally call _hideTooltip
    # Extract from the touchend registration to ~300 chars after to capture the handler body
    near = src[te_pos : te_pos + 400]
    # Unconditional hide pattern: addEventListener("touchend", () => _hideTooltip())
    # or:  addEventListener("touchend", () => { _hideTooltip(); })
    # It's unconditional if _hideTooltip appears with no conditional guard in that block
    unconditional = (
        "() => _hideTooltip()" in near
        or ("_hideTooltip" in near and "if" not in near and "activeDate" not in near and "_activeTap" not in near)
    )
    assert not unconditional, (
        "touchend still unconditionally calls _hideTooltip — tooltip cannot persist after tap"
    )


# ── AC2: Tap-to-dismiss active dot ───────────────────────────────────────────

def test_ac2_tap_toggle_dismiss_logic_exists():
    """AC2: touchstart handler has logic to dismiss the tooltip when the same dot is tapped again."""
    src = _src()
    # The tap-toggle pattern requires tracking the currently-active tap target.
    # Look for a state variable that records the active date/dot across taps.
    has_active_tap_state = (
        "_activeTapDate" in src
        or "_activeTapDot" in src
        or "activeTapDate" in src
        or "activeTap" in src
        or "_tapActive" in src
        or "tapDate" in src
    )
    assert has_active_tap_state, (
        "No tap-state variable found — AC2 requires tracking the currently-active tapped dot "
        "so a second tap on the same dot can dismiss the tooltip"
    )


def test_ac2_hide_called_on_same_dot_tap():
    """AC2: When the same dot is tapped, _hideTooltip is called (dismiss path)."""
    src = _src()
    # The touchstart handler must branch: if near.date == activeTapDate → hide; else → show
    # This requires _hideTooltip to appear inside the touchstart listener block
    ts_pos = src.find('"touchstart"')
    if ts_pos == -1:
        ts_pos = src.find("'touchstart'")
    assert ts_pos != -1, "touchstart listener missing from weight-chart.js"
    # Look in a generous window around the touchstart block
    near = src[ts_pos : ts_pos + 600]
    assert "_hideTooltip" in near, (
        "touchstart handler must call _hideTooltip for the dismiss path (AC2: tap same dot again)"
    )


# ── AC3: Switching tooltip to a different dot ─────────────────────────────────

def test_ac3_switch_dot_updates_state():
    """AC3: touchstart updates the active-tap state when a different dot is tapped."""
    src = _src()
    # The show-path must update the active-tap variable before/after calling _showTooltip
    # Since this is in the same touchstart block, just verify _showTooltip + state variable coexist
    ts_pos = src.find('"touchstart"')
    if ts_pos == -1:
        ts_pos = src.find("'touchstart'")
    assert ts_pos != -1, "touchstart listener missing"
    near = src[ts_pos : ts_pos + 700]
    has_show = "_showTooltip" in near
    has_state = any(v in near for v in (
        "_activeTapDate", "_activeTapDot", "activeTapDate", "activeTap", "_tapActive", "tapDate"
    ))
    assert has_show and has_state, (
        "touchstart block must both call _showTooltip and update active-tap state "
        "so switching to a different dot works (AC3)"
    )


# ── AC4: touchend no longer unconditionally hides tooltip ─────────────────────

def test_ac4_touchend_not_unconditional_hide():
    """AC4: The unconditional `svg.addEventListener('touchend', () => _hideTooltip())` is gone."""
    src = _src()
    # This is the exact old pattern — it must not appear verbatim
    old_pattern_variations = [
        'addEventListener("touchend", () => _hideTooltip())',
        "addEventListener('touchend', () => _hideTooltip())",
        "addEventListener(\"touchend\", () => _hideTooltip())",
    ]
    for pat in old_pattern_variations:
        assert pat not in src, (
            f"Old unconditional touchend hide pattern still present: {pat!r}"
        )


# ── AC5: Today's persistent labels are unaffected ─────────────────────────────

def test_ac5_today_persistent_labels_unaffected():
    """AC5: isMobile / today-label code paths from #515 are still present after the fix."""
    src = _src()
    assert "isMobile" in src, "isMobile variable removed — today persistent labels from #515 broken"
    assert "trend_kg" in src, "trend_kg reference removed — today label from #515 broken"
    assert "gap_kg" in src, "gap_kg reference removed — today label from #515 broken"
    assert "480" in src, "480px breakpoint removed — isMobile detection from #515 broken"


# ── AC6: Desktop mouse hover behavior unchanged ───────────────────────────────

def test_ac6_mousemove_listener_unchanged():
    """AC6: mousemove listener still calls _showTooltip and _hideTooltip for desktop hover."""
    src = _src()
    assert "mousemove" in src, "mousemove listener missing — desktop hover broken"
    assert "mouseleave" in src, "mouseleave listener missing — desktop hover-out broken"
    mm_pos = src.find("mousemove")
    near = src[mm_pos : mm_pos + 300]
    assert "_showTooltip" in near or "_hideTooltip" in near or "_findNearestDot" in near, (
        "mousemove handler must still invoke tooltip logic for desktop hover (AC6)"
    )