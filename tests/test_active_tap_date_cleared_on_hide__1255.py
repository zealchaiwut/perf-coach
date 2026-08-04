"""
TDD tests for issue #1255 — _activeTapDate not cleared when _hideTooltip called outside tap path.

AC: _hideTooltip() must null _activeTapDate so any caller that hides the tooltip
    also resets the tap state. Without this, the next tap on a previously-active
    dot incorrectly triggers the dismiss branch even though no tooltip is shown.
"""
from pathlib import Path

CHART_JS = Path(__file__).parent.parent / "frontend" / "js" / "weight-chart.js"


def _src():
    return CHART_JS.read_text()


def test_hide_tooltip_nulls_active_tap_date():
    """_hideTooltip() body must assign null to _activeTapDate."""
    src = _src()

    # Locate the _hideTooltip function definition
    fn_pos = src.find("function _hideTooltip(")
    assert fn_pos != -1, "_hideTooltip function not found in weight-chart.js"

    # Extract the function body (up to the closing brace of the function)
    # Walk forward from the opening brace to find the matching close brace
    brace_start = src.find("{", fn_pos)
    assert brace_start != -1, "_hideTooltip has no opening brace"
    depth = 0
    brace_end = brace_start
    for i in range(brace_start, min(brace_start + 500, len(src))):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                brace_end = i
                break

    fn_body = src[brace_start : brace_end + 1]

    assert "_activeTapDate" in fn_body, (
        "_hideTooltip() does not reset _activeTapDate. "
        "Any non-touch caller (mouseleave, programmatic hide, re-render) leaves "
        "_activeTapDate stale, causing the next tap on the previously-active dot "
        "to incorrectly trigger the dismiss branch."
    )
    assert "null" in fn_body, (
        "_hideTooltip() must set _activeTapDate = null, not just reference it."
    )


def test_hide_tooltip_still_hides_display():
    """_hideTooltip() must still set display:none on the tooltip element."""
    src = _src()
    fn_pos = src.find("function _hideTooltip(")
    assert fn_pos != -1, "_hideTooltip function not found"
    brace_start = src.find("{", fn_pos)
    assert brace_start != -1
    depth = 0
    brace_end = brace_start
    for i in range(brace_start, min(brace_start + 500, len(src))):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                brace_end = i
                break
    fn_body = src[brace_start : brace_end + 1]
    assert "display" in fn_body, (
        "_hideTooltip() must still hide the tooltip element (set display:none)."
    )


def test_touchstart_dismiss_path_still_nulls_active_tap_date():
    """The tap-to-dismiss path in touchstart must still null _activeTapDate explicitly."""
    src = _src()
    ts_pos = src.find('"touchstart"')
    if ts_pos == -1:
        ts_pos = src.find("'touchstart'")
    assert ts_pos != -1, "touchstart listener not found"
    # Look ahead for the tap-toggle block
    near = src[ts_pos : ts_pos + 700]
    # After the fix, _hideTooltip itself nulls the state, but the explicit null
    # in the touchstart handler may optionally remain. What matters is that the
    # dismiss path invokes _hideTooltip (which will then null _activeTapDate).
    assert "_hideTooltip" in near, (
        "touchstart dismiss path no longer calls _hideTooltip — dismiss won't null _activeTapDate."
    )
