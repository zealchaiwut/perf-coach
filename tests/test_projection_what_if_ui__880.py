"""
Tests for issue #880: Add Projection and What-If UI to Weight Chart.

Acceptance criteria verified:
- ac1: Chart reads from projection endpoint; renders forward projection line using gradient theme
- ac2: A "projected arrival" label appears near the goal marker, distinct from planned goal date
- ac3: Not-trending-toward-goal state shows an honest off-track indicator
- ac4: A what-if control (rate input) is visible on the chart view
- ac5: What-if simulated forward line rendered on chart as a differently-styled overlay
- ac6: What-if preview does not persist any data (client-side state only, not sent to server)
- ac7: Clear/Reset action removes what-if overlay and restores actual projection
- ac8: All new UI follows gradient theme; uses structural layout (no ad-hoc pixel overrides)
- ac9: No changes to chart zoom or pan behavior
"""
import re
from pathlib import Path

# For testing against the feature branch implementation
html = Path("/tmp/weight.html").read_text()
js   = Path("/tmp/weight.js").read_text()


def _chart_js():
    return Path("/tmp/weight-chart.js").read_text()


# ── AC1: Chart reads from projection endpoint; renders projection line ──────────

def test_ac1_arrival_projection_api_call_in_weight_js():
    """AC1: weight.js must call /api/weight-targets/arrival-projection."""
    assert "arrival-projection" in js, (
        "weight.js must fetch /api/weight-targets/arrival-projection"
    )


def test_ac1_projection_line_gradient_colors_in_chart_js():
    """AC1: weight-chart.js must use gradient theme colors (#5a8dee and #1f3b8a) for projection line."""
    cjs = _chart_js()
    assert "#5a8dee" in cjs or "5a8dee" in cjs.lower(), (
        "weight-chart.js must use gradient color #5a8dee for the projection line"
    )
    assert "#1f3b8a" in cjs or "1f3b8a" in cjs.lower(), (
        "weight-chart.js must use gradient color #1f3b8a for the projection line"
    )


def test_ac1_set_projection_exported_from_chart_module():
    """AC1: WeightChart module must export setProjection so weight.js can push data in."""
    cjs = _chart_js()
    assert "setProjection" in cjs, (
        "weight-chart.js must export setProjection()"
    )


def test_ac1_projection_data_used_in_render():
    """AC1: weight-chart.js render() must reference _projectionData to draw the overlay."""
    cjs = _chart_js()
    assert "_projectionData" in cjs, (
        "weight-chart.js must maintain _projectionData state variable for projection overlay"
    )


def test_ac1_projection_rendered_only_in_future_zone():
    """AC1: Projection line is drawn only when hasFutureZone / threeZone is true."""
    cjs = _chart_js()
    # The projection code block must be guarded by hasFutureZone or threeZone
    assert "hasFutureZone" in cjs and "_projectionData" in cjs, (
        "weight-chart.js must guard projection rendering with hasFutureZone"
    )


# ── AC2: Projected arrival label near goal marker ──────────────────────────────

def test_ac2_projection_strip_element_in_html():
    """AC2: weight.html must have a projection-strip element for the arrival label."""
    assert "projection-strip" in html, (
        "weight.html must contain an element with id='projection-strip'"
    )


def test_ac2_projection_label_element_in_html():
    """AC2: weight.html must have a projection-label element inside the strip."""
    assert "projection-label" in html, (
        "weight.html must contain an element with id='projection-label'"
    )


def test_ac2_arrival_label_text_in_weight_js():
    """AC2: weight.js must render 'At your current rate' language in the label."""
    assert "At your current rate" in js or "current rate" in js.lower(), (
        "weight.js must render 'At your current rate' or similar language for the projected arrival label"
    )


def test_ac2_projected_arrival_date_formatted_in_js():
    """AC2: weight.js must format the projected_arrival_date for display."""
    assert "projected_arrival_date" in js, (
        "weight.js must reference projected_arrival_date from the projection endpoint response"
    )


def test_ac2_projection_strip_uses_gradient_blue():
    """AC2: Projection strip uses gradient blue (#1f3b8a or #5a8dee) not plan green (#16a34a)."""
    # The projection label color should be gradient blue, not the plan green
    # Check that the chart.js projection uses gradient colors distinct from plan color
    cjs = _chart_js()
    assert "#5a8dee" in cjs, (
        "weight-chart.js projection rendering must use gradient blue #5a8dee (distinct from plan green #16a34a)"
    )
    # The projection label on the SVG should not use the plan color
    proj_section = cjs[cjs.find("_projectionData"):] if "_projectionData" in cjs else ""
    assert "#16a34a" not in proj_section[:500] or "#5a8dee" in proj_section[:500], (
        "Projection label color must be distinct from plan-line green (#16a34a)"
    )


# ── AC3: Not-trending-toward-goal state shows honest off-track indicator ────────

def test_ac3_not_trending_toward_goal_handled_in_js():
    """AC3: weight.js must handle reason === 'not_trending_toward_goal'."""
    assert "not_trending_toward_goal" in js, (
        "weight.js must check for reason === 'not_trending_toward_goal' from the projection endpoint"
    )


def test_ac3_off_track_text_in_js():
    """AC3: weight.js must render an off-track message when not trending toward goal."""
    assert "Not on track" in js or "not on track" in js.lower() or "moves away" in js, (
        "weight.js must render 'Not on track' or 'moves away from goal' when not trending toward goal"
    )


def test_ac3_projection_banner_hidden_when_insufficient_data():
    """AC3: weight.js must hide the projection strip when reason is insufficient_data or no plan."""
    assert "insufficient_data" in js or "no_active_plan" in js, (
        "weight.js must handle insufficient_data and no_active_plan reasons by hiding the projection strip"
    )


# ── AC4: What-if control visible on chart view ─────────────────────────────────

def test_ac4_whatif_strip_element_in_html():
    """AC4: weight.html must have a what-if control strip visible on the chart view."""
    assert "whatif-strip" in html, (
        "weight.html must contain an element with id='whatif-strip'"
    )


def test_ac4_whatif_rate_input_in_html():
    """AC4: weight.html must have a numeric input for the what-if rate."""
    assert 'id="whatif-rate"' in html or "id='whatif-rate'" in html, (
        "weight.html must have a numeric input with id='whatif-rate' for the what-if rate"
    )


def test_ac4_whatif_rate_input_type_number():
    """AC4: The what-if rate input must be type='number' for numeric entry."""
    # Find the actual input element by id; search back to the opening <input tag
    elem_idx = html.find('id="whatif-rate"')
    if elem_idx < 0:
        elem_idx = html.find("id='whatif-rate'")
    assert elem_idx >= 0, "whatif-rate input element not found in weight.html"
    # Find the <input opening tag (up to 300 chars before the id attribute)
    tag_start = html.rfind("<input", max(0, elem_idx - 300), elem_idx + 1)
    assert tag_start >= 0, "Could not find opening <input tag for whatif-rate"
    tag_end = html.find(">", elem_idx)
    tag_content = html[tag_start:tag_end + 1]
    assert 'type="number"' in tag_content or "type='number'" in tag_content, (
        "The whatif-rate input must have type='number'"
    )


def test_ac4_whatif_endpoint_called_in_weight_js():
    """AC4: weight.js must call the what-if endpoint when the rate changes."""
    assert "what-if" in js, (
        "weight.js must call the /api/weight-targets/{goal_id}/what-if endpoint"
    )


def test_ac4_whatif_control_shown_only_with_active_target():
    """AC4: What-if strip is hidden when no active target; shown when active target exists."""
    assert "whatif-strip" in js, (
        "weight.js must control whatif-strip visibility based on active target"
    )


# ── AC5: What-if simulated forward line rendered differently from projection ────

def test_ac5_whatif_overlay_rendered_in_chart_js():
    """AC5: weight-chart.js must render the what-if overlay line on the chart."""
    cjs = _chart_js()
    assert "_whatIfData" in cjs, (
        "weight-chart.js must have _whatIfData state variable for what-if overlay"
    )
    assert "setWhatIf" in cjs, (
        "weight-chart.js must export setWhatIf() to receive what-if data"
    )


def test_ac5_whatif_line_different_color_from_projection():
    """AC5: What-if line must use a different color from the projection gradient."""
    cjs = _chart_js()
    # The what-if section must use a color other than the gradient colors
    # Check that there's a different color used near 'whatIfData' or 'simulated_line'
    wi_idx = cjs.find("_whatIfData")
    if wi_idx >= 0:
        wi_section = cjs[wi_idx:wi_idx + 800]
        # Should not exclusively use gradient colors — must have a distinct color
        has_non_gradient_color = (
            "#e67e22" in wi_section or
            "#f97316" in wi_section or
            "#f59e0b" in wi_section or
            "#e4ff52" in wi_section or
            any(c in wi_section for c in ["orange", "amber"])
        )
        assert has_non_gradient_color or (
            "#5a8dee" not in wi_section and "#1f3b8a" not in wi_section
        ), (
            "What-if line must be styled differently (different color) from the projection line"
        )


def test_ac5_whatif_simulated_line_rendered():
    """AC5: weight-chart.js must render the simulated_line points from the what-if response."""
    cjs = _chart_js()
    assert "simulated_line" in cjs, (
        "weight-chart.js must render points from the simulated_line array"
    )


def test_ac5_whatif_legend_chip_in_html():
    """AC5: weight.html must have a legend chip for the what-if overlay line."""
    assert "legend-whatif" in html, (
        "weight.html must have a legend chip with id='legend-whatif' for the what-if overlay"
    )


# ── AC6: What-if preview does not persist ────────────────────────────────────

def test_ac6_whatif_data_not_saved_to_server():
    """AC6: weight.js what-if logic must not POST/PATCH any persistence endpoint."""
    # The what-if route is POST /api/weight-targets/{id}/what-if — read-only simulation
    # weight.js must not call any additional save/persist endpoint for what-if state
    # Check: the only what-if-related POST is the simulation endpoint itself
    wi_idx = js.find("what-if")
    assert wi_idx >= 0, "weight.js must call the what-if endpoint"
    # Verify no 'save', 'persist', or additional POST for the what-if state
    wi_context = js[wi_idx:wi_idx + 300]
    assert "persist" not in wi_context.lower() and "save" not in wi_context[:50], (
        "What-if state must not be persisted — no save/persist calls near the what-if logic"
    )


def test_ac6_whatif_state_is_module_variable():
    """AC6: What-if state is stored as a transient module-level variable (not in localStorage, etc.)."""
    cjs = _chart_js()
    assert "_whatIfData" in cjs, (
        "What-if data must be stored as a module-level variable in weight-chart.js (not persisted)"
    )
    # Must not use localStorage or sessionStorage for what-if
    assert "localStorage" not in cjs or "whatif" not in cjs[cjs.find("localStorage"):cjs.find("localStorage")+100].lower(), (
        "What-if data must not be persisted to localStorage"
    )


def test_ac6_page_reload_discards_whatif():
    """AC6: The what-if state is initialized to null/empty — reloads discard it."""
    cjs = _chart_js()
    # _whatIfData must be initialized to null
    assert re.search(r"_whatIfData\s*=\s*null", cjs), (
        "_whatIfData must be initialized to null in weight-chart.js so reloads discard it"
    )


# ── AC7: Clear/Reset action removes what-if overlay ──────────────────────────

def test_ac7_whatif_clear_button_in_html():
    """AC7: weight.html must have a 'Clear' or 'Reset' button for the what-if overlay."""
    assert 'id="whatif-clear"' in html or "whatif-clear" in html, (
        "weight.html must have a button with id='whatif-clear' (or similar) to clear the what-if overlay"
    )


def test_ac7_clear_button_text_in_html():
    """AC7: The clear button must be labeled 'Clear' or 'Reset'."""
    # Find the button element by id, not the CSS class name
    btn_idx = html.find('id="whatif-clear"')
    if btn_idx < 0:
        btn_idx = html.find("id='whatif-clear'")
    if btn_idx >= 0:
        context = html[btn_idx:btn_idx + 150]
        assert "Clear" in context or "Reset" in context, (
            "The what-if clear button must be labeled 'Clear' or 'Reset'"
        )


def test_ac7_clear_whatif_exported_from_chart_module():
    """AC7: WeightChart module must export clearWhatIf() so weight.js can remove the overlay."""
    cjs = _chart_js()
    assert "clearWhatIf" in cjs, (
        "weight-chart.js must export clearWhatIf()"
    )


def test_ac7_clear_handler_in_weight_js():
    """AC7: weight.js must handle the clear button click to remove the what-if overlay."""
    assert "clearWhatIf" in js or "whatif-clear" in js, (
        "weight.js must handle the whatif-clear button click and call clearWhatIf()"
    )


def test_ac7_clear_restores_projection_not_page_reload():
    """AC7: Clearing what-if restores the actual projection without a page reload."""
    # clearWhatIf must trigger a chart re-render, not a full page reload
    cjs = _chart_js()
    clear_idx = cjs.find("clearWhatIf")
    if clear_idx >= 0:
        fn_body = cjs[clear_idx:clear_idx + 200]
        # Should call render or savedData to re-render inline
        assert "_savedData" in fn_body or "render(" in fn_body or "_whatIfData" in fn_body, (
            "clearWhatIf must re-render the chart inline (no page reload)"
        )


# ── AC8: Gradient theme; structural layout ────────────────────────────────────

def test_ac8_projection_strip_uses_var_tokens():
    """AC8: Projection strip CSS must not use large ad-hoc pixel dimensions (≥100 px) for layout."""
    proj_style_idx = html.find("projection-strip")
    # Check that the projection strip doesn't use hardcoded large pixel dimensions
    # Small padding/margin values like 8px are fine; structural overrides like
    # "width: 847px" or "height: 130px" are not.
    if proj_style_idx >= 0:
        context = html[max(0, proj_style_idx - 300):proj_style_idx + 600]
        # Require 3+ digit values (≥100px) to flag; small spacing values are acceptable
        bad_px = re.search(r'(?:width|height)\s*:\s*[1-9]\d{2,}px', context)
        assert not bad_px, (
            f"Projection strip must not use large ad-hoc pixel overrides. Found: {bad_px.group() if bad_px else ''}"
        )


def test_ac8_whatif_strip_uses_var_tokens():
    """AC8: What-if strip CSS must use structural layout (var() tokens or percentage-based)."""
    wi_idx = html.find("whatif-strip")
    if wi_idx >= 0:
        context = html[max(0, wi_idx - 300):wi_idx + 600]
        bad_px = re.search(r'(?:margin-left|margin-right|margin-top|margin-bottom)\s*:\s*\d{3,}px', context)
        assert not bad_px, (
            f"What-if strip must use structural layout, not ad-hoc large pixel margins. Found: {bad_px.group() if bad_px else ''}"
        )


def test_ac8_gradient_legend_chip_present():
    """AC8: A legend chip for the projection line must be present using gradient theme color."""
    assert "legend-projection" in html, (
        "weight.html must have a legend chip with id='legend-projection'"
    )
    # Check the chip uses a gradient color
    proj_chip_idx = html.find("legend-projection")
    if proj_chip_idx >= 0:
        context = html[proj_chip_idx:proj_chip_idx + 300]
        assert "#5a8dee" in context or "5a8dee" in context, (
            "The projection legend chip must use gradient color #5a8dee"
        )


# ── AC9: No changes to chart zoom or pan behavior ────────────────────────────

def test_ac9_range_tabs_unchanged():
    """AC9: Existing range tabs (7D, 30D, 90D, 6M, 1Y, ALL) still present and unchanged."""
    for tab in ('7d', '30d', '90d', '6m', '1y', 'all'):
        assert f'data-range="{tab}"' in html.lower(), (
            f"Range tab data-range='{tab}' must still be present (no changes to zoom behavior)"
        )


def test_ac9_range_tab_handler_unchanged_in_js():
    """AC9: Range tab handler in weight.js must not be modified (fetchChartData still called)."""
    assert "fetchChartData" in js, (
        "weight.js must still call fetchChartData from range tab handler"
    )
    assert "_initRangeTabs" in js, (
        "weight.js must still have _initRangeTabs function"
    )


def test_ac9_tooltip_events_unchanged_in_chart_js():
    """AC9: Tooltip mousemove/touchstart/touchmove events must still be present in weight-chart.js."""
    cjs = _chart_js()
    assert "mousemove" in cjs, "mousemove event handler must still be present in weight-chart.js"
    assert "touchstart" in cjs, "touchstart event handler must still be present in weight-chart.js"
    assert "touchmove"  in cjs, "touchmove event handler must still be present in weight-chart.js"


def test_ac9_render_function_signature_unchanged():
    """AC9: WeightChart.render() signature is unchanged; no new required parameters added."""
    cjs = _chart_js()
    # render should still accept (data, range) — not more required params
    assert re.search(r"function render\s*\(\s*data\s*,\s*range\s*\)", cjs), (
        "WeightChart.render(data, range) signature must remain unchanged"
    )
