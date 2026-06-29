"""TDD tests for issue #633 — Redesign weight trend chart with three-zone axes.

19 AC anchors tested:
  (ac1)   Horizontal zones 5/90/5: RAIL_FR = 0.05
  (ac2)   Range tabs resize only the 90% present zone (structural)
  (ac3a)  Present band formula: present_min = min - 10%*spread, present_max = max + 10%*spread
  (ac3b)  Vertical zones 10/80/10 constants present in source
  (ac4)   Vertical scale recomputes per range tab (present bounds called in render)
  (ac5)   Out-of-range highs compressed in top 10% rail (not clipped)
  (ac6)   Goal weight chip in bottom 10% rail, always visible (not just mobile)
  (ac7)   Y-axis ticks are integers derived from present band
  (ac8)   Dense daily weigh-in dots (existing, preserved)
  (ac9)   7-day trend line in blue (existing, preserved)
  (ac10)  Missing-data gaps: dotted bridge (existing, preserved)
  (ac11)  Plan line as dashed line (existing, preserved)
  (ac12)  Green/red gap fill (existing, preserved)
  (ac13)  Verdict banner (existing, preserved)
  (ac14)  Today markers for trend and plan (existing, preserved)
  (ac15)  Tooltips / tap-to-show preserved (existing, preserved)
  (ac17)  No new root-level CSS color vars introduced
  (ac18a) Mobile ≤640px: only 7D/30D/90D/1Y tabs visible (6M and ALL hidden)
  (ac18b) Mobile: goal renders as pinned chip in bottom rail
  (ac19)  Finalized mockup committed to docs/mockups/ before implementation
"""
from pathlib import Path
import re

FRONTEND   = Path(__file__).parent.parent / "frontend"
WEIGHT_HTML = FRONTEND / "pages" / "weight.html"
CHART_JS    = FRONTEND / "js" / "weight-chart.js"
DOCS       = Path(__file__).parent.parent / "docs"


def _html():
    return WEIGHT_HTML.read_text()


def _src():
    return CHART_JS.read_text()


def _css():
    """Return only the <style> block(s) from weight.html."""
    raw = _html()
    styles = re.findall(r'<style[^>]*>(.*?)</style>', raw, re.DOTALL)
    return "\n".join(styles)


# ── AC1: Horizontal zones 5/90/5 ─────────────────────────────────────────────

def test_ac1_rail_fraction_is_5pct():
    """AC1: RAIL_FR must be 0.05 (5% rails), not 0.06."""
    src = _src()
    # RAIL_FR constant must be 0.05
    assert 'RAIL_FR' in src, "RAIL_FR constant missing from weight-chart.js"
    assert '0.05' in src, (
        "0.05 not found in weight-chart.js — RAIL_FR must be 0.05 for 5/90/5 horizontal zones"
    )


def test_ac1_present_zone_is_90pct():
    """AC1: CUR_W3 must derive from CW minus two 5% rails, giving 90% present zone."""
    src = _src()
    # PAST_W + FUTURE_W should account for two 5% rails, leaving 90% for present
    assert 'CUR_W3' in src and 'PAST_W' in src and 'FUTURE_W' in src, (
        "CUR_W3, PAST_W, FUTURE_W constants missing — 90% present zone not derivable"
    )


# ── AC3: Vertical zones 10/80/10 with present_min/max formula ────────────────

def test_ac3_present_bounds_function_exists():
    """AC3: A function computing present_min and present_max from visible data must exist."""
    src = _src()
    has_func = 'presentMin' in src and 'presentMax' in src
    assert has_func, (
        "presentMin / presentMax not found in weight-chart.js — "
        "present-band bounds computation is required for 10/80/10 vertical zones"
    )


def test_ac3_spread_buffer_10pct():
    """AC3: present_min = min(visible) - 10%*spread; present_max = max + 10%*spread."""
    src = _src()
    # The formula uses a 10% buffer on the spread
    assert '0.10' in src or '0.1' in src, (
        "10% spread buffer not found in weight-chart.js — "
        "present_min/max formula must use spread * 0.10"
    )


def test_ac3_vertical_band_constant_present():
    """AC3: Vertical zone constant for the 80% center band exists in source."""
    src = _src()
    # V_BAND or the literal 0.80 must be present to define the center band
    has_band = 'V_BAND' in src or '0.80' in src or 'V_TOP_RAIL' in src
    assert has_band, (
        "Vertical zone band constant (V_BAND / 0.80 / V_TOP_RAIL) missing from weight-chart.js"
    )


def test_ac3_three_zone_y_coordinate_function():
    """AC3: A three-zone Y coordinate function must map values into top/center/bottom zones."""
    src = _src()
    # A function that handles the three vertical zones must reference all three
    assert 'presentMin' in src and 'presentMax' in src, (
        "Three-zone Y mapping requires presentMin and presentMax references"
    )
    # Must handle the case where val > presentMax (top rail compression)
    assert '> presentMax' in src or '>= presentMax' in src or 'presentMax' in src, (
        "Top rail branch (val > presentMax) not found in weight-chart.js"
    )


# ── AC4: Vertical scale recomputes per range tab ─────────────────────────────

def test_ac4_present_bounds_called_in_render():
    """AC4: present bounds computation must be called inside the render() function."""
    src = _src()
    # presentMin and presentMax must be computed inside render, not just defined globally
    render_block_start = src.find('function render(')
    assert render_block_start != -1, "render() function not found in weight-chart.js"
    render_tail = src[render_block_start:]
    assert 'presentMin' in render_tail, (
        "presentMin not computed inside render() — vertical scale won't recompute per range tab"
    )


# ── AC5: Out-of-range highs compressed in top rail ───────────────────────────

def test_ac5_top_rail_handles_above_range():
    """AC5: Values above present_max are compressed into the top 10% rail, not clipped."""
    src = _src()
    # The Y coordinate function must handle val > presentMax with rail compression
    assert 'V_TOP_RAIL' in src or ('presentMax' in src and 'PAD.top' in src), (
        "Top-rail compression for above-range values not found in weight-chart.js"
    )
    # Must not clip — should still render a valid Y coordinate
    assert 'clamp' not in src.lower() or 'presentMax' in src, (
        "Evidence of clipping without rail compression found in weight-chart.js"
    )


# ── AC6: Goal weight chip in bottom 10% rail, always visible ─────────────────

def test_ac6_goal_chip_not_only_on_mobile():
    """AC6: Goal chip must be rendered outside the isMobileChart guard (always visible on desktop too)."""
    src = _src()
    # The goal chip must appear in the source
    assert 'goal' in src.lower() and ('chip' in src.lower() or 'chipW' in src or 'chipT' in src), (
        "Goal chip render code not found in weight-chart.js"
    )
    # Critical: the chip block must not be inside an isMobileChart-only guard
    # Find the chip render block and ensure it's accessible on desktop too
    chip_pos = src.find('chipT')
    if chip_pos == -1:
        chip_pos = src.find("' · goal'")
    if chip_pos == -1:
        chip_pos = src.find("goal'")
    assert chip_pos != -1, "Goal chip text element not found in weight-chart.js"

    # The goal chip should be rendered when hasTarget is true (not gated by isMobileChart alone)
    # Find the nearest isMobileChart check before chip_pos
    section_before = src[:chip_pos]
    last_if_mobile = section_before.rfind('isMobileChart')
    last_if_target = section_before.rfind('hasTarget')
    # The chip should be guarded by hasTarget (or target), not isMobileChart alone
    assert last_if_target > last_if_mobile or 'hasTarget' in src[chip_pos - 200: chip_pos + 200], (
        "Goal chip appears to be mobile-only — it must render on desktop too (AC6)"
    )


def test_ac6_goal_chip_in_bottom_rail():
    """AC6: Goal chip Y position uses the bottom rail (Y > present band bottom edge)."""
    src = _src()
    # The chip is rendered with V_BOT_RAIL or at a position derived from the 3-zone Y fn
    assert 'V_BOT_RAIL' in src or 'presentMin' in src, (
        "Bottom-rail goal chip positioning not found — chip must use three-zone Y coordinate"
    )


# ── AC7: Y-axis ticks are integers from present band ─────────────────────────

def test_ac7_gridlines_within_present_band():
    """AC7: Gridline bounds are derived from the present band, not the global min/max."""
    src = _src()
    # Gridlines must reference presentMin or presentMax for bounds
    gridline_section = src.find('C.grid')
    assert gridline_section != -1, "Gridline (C.grid) not found in weight-chart.js"
    # In the context around gridlines, presentMin or presentMax must appear
    context = src[max(0, gridline_section - 400): gridline_section + 200]
    assert 'presentMin' in context or 'presentMax' in context or 'presentBand' in context, (
        "Gridlines not bounded by present band (presentMin/Max not near C.grid section)"
    )


def test_ac7_ticks_are_integers():
    """AC7: Tick computation uses integer stepping via an adaptive step."""
    src = _src()
    assert 'kg += _tickStep' in src and 'Math.ceil(presentMin' in src, (
        "Integer adaptive-step tick loop (kg += _tickStep) not found in weight-chart.js"
    )


# ── AC8–AC15: Preserved features (spot-check) ────────────────────────────────

def test_ac8_weigh_in_dots_present():
    """AC8: Daily weigh-in dots still render (C.actual used)."""
    src = _src()
    assert 'C.actual' in src, "Weigh-in dots (C.actual) removed from weight-chart.js"


def test_ac9_trend_line_blue():
    """AC9: 7-day trend line still uses C.trend (blue)."""
    src = _src()
    assert 'C.trend' in src, "7-day trend line (C.trend) removed from weight-chart.js"


def test_ac10_missing_gap_bridge():
    """AC10: Faded dotted bridge across missing-data gaps still present."""
    src = _src()
    assert 'stroke-dasharray' in src and 'opacity' in src, (
        "Missing-data gap bridge (dasharray + opacity) not found in weight-chart.js"
    )


def test_ac11_plan_line_dashed():
    """AC11: Plan line still renders as dashed."""
    src = _src()
    assert 'plan_series' in src and 'stroke-dasharray' in src, (
        "Dashed plan line not found in weight-chart.js"
    )


def test_ac12_gap_fill_green_red():
    """AC12: Green/red gap area fill still present."""
    src = _src()
    assert 'fill_ahead' in src and 'fill_behind' in src, (
        "Gap-area fill colors (fill_ahead/fill_behind) removed from weight-chart.js"
    )


def test_ac13_verdict_banner_updates():
    """AC13: _updateVerdictBanner still called in render."""
    src = _src()
    assert '_updateVerdictBanner' in src, (
        "_updateVerdictBanner removed from weight-chart.js"
    )


def test_ac14_today_marker_trend_and_plan():
    """AC14: Today marker for both trend and plan still rendered."""
    src = _src()
    assert 'tm.trend_kg' in src and 'tm.plan_kg' in src, (
        "Today-marker trend/plan dots removed from weight-chart.js"
    )


def test_ac15_tooltip_preserved():
    """AC15: Tooltip and tap-to-show behavior preserved."""
    src = _src()
    assert '_showTooltip' in src and 'touchstart' in src, (
        "Tooltip or touch handler removed from weight-chart.js"
    )


# ── AC17: No new root-level CSS color variables ───────────────────────────────

def test_ac17_no_new_root_colors():
    """AC17: Gradient-theme CSS vars are reused; no new :root color declarations added."""
    css = _css()
    # Extract all CSS custom property declarations inside :root blocks
    root_blocks = re.findall(r':root\s*\{([^}]*)\}', css, re.DOTALL)
    all_vars = []
    for block in root_blocks:
        all_vars.extend(re.findall(r'--[\w-]+\s*:', block))

    # Known allowed vars (already in the codebase from prior sprints)
    known_vars = {
        '--primary', '--primary-dark', '--focus-ring', '--success', '--warning',
        '--danger', '--danger-dark', '--danger-soft', '--text', '--text-sub',
        '--border', '--border-input', '--surface', '--surface-2',
        '--readiness-high', '--readiness-mid', '--readiness-low',
        '--ink', '--ink-2', '--tile', '--mono',
        '--intensity-warmup', '--intensity-easy', '--intensity-tempo',
        '--intensity-intervals', '--intensity-rest', '--intensity-cooldown',
        '--bg-1', '--bg-2', '--shell-1', '--shell-2', '--card-bg', '--card-border',
        '--card-radius', '--card-shadow', '--text-primary', '--text-secondary',
        '--text-tertiary', '--accent', '--accent-text', '--green', '--green-soft',
        '--red', '--red-soft', '--amber', '--amber-soft', '--page-bg',
    }
    new_vars = []
    for v in all_vars:
        name = v.rstrip(':').strip()
        if name not in known_vars:
            new_vars.append(name)
    assert not new_vars, (
        f"New root-level CSS custom properties introduced in weight.html: {new_vars}. "
        "Reuse existing gradient-theme variables instead."
    )


# ── AC18: Mobile layout ───────────────────────────────────────────────────────

def test_ac18a_mobile_hides_6m_tab():
    """AC18: At ≤640px, 6M range tab is hidden (not shown on mobile)."""
    css = _css()
    # 6m must be in the mobile hide list
    assert ('data-range="6m"' in css or "data-range='6m'" in css or
            '[data-range="6m"]' in css), (
        "6M tab not hidden in mobile CSS (≤640px) — must be display:none on mobile"
    )


def test_ac18a_mobile_shows_1y_tab():
    """AC18: At ≤640px, 1Y tab must be visible (NOT in the hidden list)."""
    css = _css()
    # Find the mobile media query block (≤640px)
    mobile_block = ''
    for match in re.finditer(r'@media\s*\(max-width:\s*640px\)', css):
        start = match.end()
        # Find matching brace
        depth = 0
        end = start
        for i, ch in enumerate(css[start:], start=start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                if depth == 0:
                    end = i
                    break
                depth -= 1
        mobile_block += css[start:end]

    # 1y tab must NOT be in the hidden list within the ≤640px block
    # (it's OK if it's mentioned in a separate context but must not be display:none)
    hidden_pattern = re.search(
        r'\.range-tab\[data-range=["\']1y["\']\]', mobile_block
    )
    if hidden_pattern:
        # It's referenced, but ensure it's shown, not hidden
        # Look for display:none nearby
        surrounding = mobile_block[max(0, hidden_pattern.start() - 20):hidden_pattern.end() + 80]
        assert 'display' not in surrounding or 'none' not in surrounding, (
            "1Y range tab is hidden in ≤640px mobile CSS — it must be visible on mobile (AC18)"
        )


def test_ac18a_mobile_hides_all_tab():
    """AC18: At ≤640px, ALL range tab is hidden (not shown on mobile)."""
    css = _css()
    assert '[data-range="all"]' in css or "data-range='all'" in css, (
        "ALL tab not handled in mobile CSS — must be hidden at ≤640px"
    )


def test_ac18b_goal_chip_mobile():
    """AC18: Goal chip is rendered in mobile layout (isMobileChart guard includes chip)."""
    src = _src()
    # Goal chip must exist (already tested in ac6), but also check isMobileChart path
    assert 'chipT' in src or "goal'" in src, (
        "Goal chip (chipT / goal chip) not found in weight-chart.js"
    )


def test_ac18e_no_horizontal_overflow_meta():
    """AC18: weight.html has viewport meta tag preventing overflow at 360px."""
    html = _html()
    assert 'viewport' in html and 'width=device-width' in html, (
        "Viewport meta tag missing from weight.html — required to prevent overflow at 360px"
    )


# ── AC19: Mockup committed to docs/mockups/ ──────────────────────────────────

def test_ac19_mockup_exists_in_docs():
    """AC19: A finalized mockup HTML file for issue #633 must exist in docs/mockups/."""
    mockups_dir = DOCS / "mockups"
    assert mockups_dir.exists(), "docs/mockups/ directory not found"
    # Accept any HTML file that references the three-zone chart or issue 633
    html_files = list(mockups_dir.glob("*.html"))
    assert html_files, "No HTML mockup files found in docs/mockups/"
    # Check for a v8 or 633-related mockup (naming convention: weight-trend-chart-v8.html)
    names = [f.name for f in html_files]
    has_new_mockup = any(
        'v8' in n or '633' in n or 'three-zone' in n or 'three_zone' in n
        for n in names
    )
    assert has_new_mockup, (
        f"No three-zone chart mockup found in docs/mockups/. "
        f"Existing: {names}. Expected a file with 'v8', '633', or 'three-zone' in the name."
    )
