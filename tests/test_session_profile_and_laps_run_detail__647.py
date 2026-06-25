"""Tests for issue #647: Add Session Profile and Laps to Run Detail View.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance Criteria:
  AC1  — Session-profile (effort) bar renders ABOVE the laps section.
  AC2  — Session-profile and laps data fetched from the /full endpoint.
  AC3  — Lap table columns in order: Lap · Distance · Pace · HR · Stride · Cadence · Power.
  AC4  — Toggle switches bar chart between Pace, HR, and Power views.
  AC5  — Gradient theme and structure-over-pixel-styling conventions throughout.
  AC6  — Named constant (ZONE_2_HR_RANGE or ZONE2_HR_MIN/MAX) defined in one place; no magic numbers.
  AC7  — Z2 laps: teal row background, Z2 pill in Lap column, teal ring on chart bar.
  AC8  — Non-Z2 laps: default row style, no Z2 pill.
  AC9  — Power cell shows dash (—) when power data absent.
  AC10 — Power toggle visible even when all laps have no power; chart renders dashes.
  AC11 — No console warnings (no magic numbers, consistent dash pattern).
  AC12 — Responsive: no horizontal overflow at mobile breakpoints.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RV_HTML_PATH = _ROOT / "frontend" / "pages" / "run-view.html"
_RV_JS_PATH = _ROOT / "frontend" / "js" / "run-view.js"
_Z2_CONST_PATH = _ROOT / "frontend" / "js" / "zone2-constants.js"


def _html() -> str:
    assert _RV_HTML_PATH.exists(), f"File not found: {_RV_HTML_PATH}"
    return _RV_HTML_PATH.read_text()


def _js() -> str:
    assert _RV_JS_PATH.exists(), f"File not found: {_RV_JS_PATH}"
    return _RV_JS_PATH.read_text()


def _z2() -> str:
    assert _Z2_CONST_PATH.exists(), f"File not found: {_Z2_CONST_PATH}"
    return _Z2_CONST_PATH.read_text()


def _combined() -> str:
    return _html() + _js()


# ═════════════════════════════════════════════════════════════════════════════
# AC1 — Session-profile bar renders ABOVE the laps section
# ═════════════════════════════════════════════════════════════════════════════

def test_ac1_profile_section_defined_before_laps():
    """The session-profile section must be assigned/built before the laps section
    in the renderView function body."""
    js = _js()
    profile_idx = js.find("profileSection")
    laps_idx = js.find("lapsSection")
    assert profile_idx != -1, "run-view.js must define a profileSection variable"
    assert laps_idx != -1, "run-view.js must define a lapsSection variable"
    assert profile_idx < laps_idx, (
        "profileSection must be built before lapsSection in renderView so that "
        "the session-profile bar appears above the laps in the DOM"
    )


def test_ac1_profile_inserted_before_laps_in_dom():
    """The final innerHTML assignment must place profileSection before lapsSection."""
    js = _js()
    # Find the innerHTML assignment block
    inner_idx = js.find("innerHTML")
    assert inner_idx != -1, "run-view.js must set innerHTML to render the view"
    # In the concatenation string, profileSection must appear before lapsSection
    inner_chunk = js[inner_idx: inner_idx + 600]
    prof_pos = inner_chunk.find("profileSection")
    laps_pos = inner_chunk.find("lapsSection")
    assert prof_pos != -1, "profileSection must appear in the innerHTML assignment"
    assert laps_pos != -1, "lapsSection must appear in the innerHTML assignment"
    assert prof_pos < laps_pos, (
        "profileSection must be concatenated before lapsSection in the innerHTML "
        "assignment so the effort bar renders above the laps table in the DOM"
    )


def test_ac1_profile_uses_detected_profile_data():
    """The session-profile section must read from data.detected_profile (not
    data.unified.segments which does not exist in the /full response)."""
    js = _js()
    assert "detected_profile" in js, (
        "run-view.js must reference data.detected_profile for the session-profile "
        "bar — data.unified.segments does not exist in the /full response"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC2 — Session-profile and laps data fetched from the /full endpoint
# ═════════════════════════════════════════════════════════════════════════════

def test_ac2_only_full_endpoint_used():
    """run-view.js must call only /api/workouts/{id}/full for all data."""
    js = _js()
    assert "/full" in js, "run-view.js must call the /full endpoint"
    forbidden = ["/api/daily", "/api/habits", "/api/weight", "/api/readiness", "/api/splits"]
    for pat in forbidden:
        assert pat not in js, (
            f"run-view.js must not call {pat!r}; all data comes from /full"
        )


def test_ac2_splits_from_full_response():
    """The laps table must read from data.splits (the WorkoutSplit rows returned
    by /full), not a separate endpoint."""
    js = _js()
    assert "data.splits" in js or "splits" in js, (
        "run-view.js must use data.splits from the /full response for lap data"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC3 — Lap table column headers: Lap · Distance · Pace · HR · Stride · Cadence · Power
# ═════════════════════════════════════════════════════════════════════════════

def test_ac3_column_lap():
    """Lap table must have a 'Lap' column header."""
    js = _js()
    assert ">Lap<" in js or '"Lap"' in js or "'Lap'" in js, (
        "run-view.js must render a 'Lap' column header in the lap table"
    )


def test_ac3_column_distance():
    """Lap table must have a 'Distance' column header (not abbreviated 'Dist')."""
    js = _js()
    assert ">Distance<" in js or '"Distance"' in js or "'Distance'" in js, (
        "run-view.js must render a 'Distance' column header — the AC specifies "
        "the full word 'Distance', not 'Dist'"
    )


def test_ac3_column_pace():
    """Lap table must have a 'Pace' column header."""
    js = _js()
    assert ">Pace<" in js or '"Pace"' in js or "'Pace'" in js, (
        "run-view.js must render a 'Pace' column header in the lap table"
    )


def test_ac3_column_hr():
    """Lap table must have a 'HR' column header."""
    js = _js()
    assert ">HR<" in js or '"HR"' in js or "'HR'" in js, (
        "run-view.js must render an 'HR' column header in the lap table"
    )


def test_ac3_column_stride():
    """Lap table must have a 'Stride' column header (not 'Len (m)')."""
    js = _js()
    assert ">Stride<" in js or '"Stride"' in js or "'Stride'" in js, (
        "run-view.js must render a 'Stride' column header — the AC specifies "
        "'Stride', not 'Len (m)'"
    )


def test_ac3_column_cadence():
    """Lap table must have a 'Cadence' column header (not 'Cad (spm)')."""
    js = _js()
    assert ">Cadence<" in js or '"Cadence"' in js or "'Cadence'" in js, (
        "run-view.js must render a 'Cadence' column header — the AC specifies "
        "the full word 'Cadence', not 'Cad (spm)'"
    )


def test_ac3_column_power():
    """Lap table must have a 'Power' column header (not 'Pwr (W)')."""
    js = _js()
    assert ">Power<" in js or '"Power"' in js or "'Power'" in js, (
        "run-view.js must render a 'Power' column header — the AC specifies "
        "the full word 'Power', not 'Pwr (W)'"
    )


def test_ac3_column_order_in_source():
    """Column headers must appear in source in the order: Lap, Distance, Pace, HR,
    Stride, Cadence, Power (matching the AC specification)."""
    js = _js()
    # Find the header row in the table — look for the thead block
    thead_match = re.search(r"<thead>(.*?)</thead>", js, re.DOTALL)
    if not thead_match:
        # Try to find the headers via th class strings
        # Look for the sequence of th elements
        cols = ["Lap", "Distance", "Pace", "HR", "Stride", "Cadence", "Power"]
        positions = []
        for col in cols:
            idx = js.find(">" + col + "<")
            if idx == -1:
                idx = js.find('"' + col + '"')
            if idx == -1:
                idx = js.find("'" + col + "'")
            positions.append(idx)
        valid = [(p, c) for p, c in zip(positions, cols) if p != -1]
        assert len(valid) == 7, (
            f"All 7 column headers must be present; found only: "
            f"{[c for p, c in valid]}"
        )
        for i in range(len(valid) - 1):
            assert valid[i][0] < valid[i + 1][0], (
                f"Column '{valid[i][1]}' must appear before '{valid[i+1][1]}' "
                "in source order"
            )
    else:
        thead = thead_match.group(1)
        cols = ["Lap", "Distance", "Pace", "HR", "Stride", "Cadence", "Power"]
        positions = [thead.find(c) for c in cols]
        for i, (pos, col) in enumerate(zip(positions, cols)):
            assert pos != -1, f"Column '{col}' missing from thead"
        for i in range(len(cols) - 1):
            assert positions[i] < positions[i + 1], (
                f"Column '{cols[i]}' must appear before '{cols[i+1]}'"
            )


# ═════════════════════════════════════════════════════════════════════════════
# AC4 — Toggle switches bar chart between Pace, HR, Power
# ═════════════════════════════════════════════════════════════════════════════

def test_ac4_pace_toggle_button():
    """A Pace toggle button must be present in the lap chart controls."""
    js = _js()
    assert (
        'data-metric="pace"' in js
        or "data-metric='pace'" in js
        or '"Pace"' in js
        or "'Pace'" in js
    ), "run-view.js must include a Pace toggle button for the lap chart"


def test_ac4_hr_line_always_shown():
    """HR is now always drawn as a line on the lap chart (its own scale) rather
    than a bar-toggle option — the bar toggle is Pace/Power only."""
    js = _js()
    assert "rv2-hr-svg" in js and "polyline" in js, (
        "run-view.js must render HR as a line series (rv2-hr-svg polyline) on the lap chart"
    )
    assert "rv2-hr-key" in js, (
        "the lap chart legend must include the HR series (rv2-hr-key) with its bpm range"
    )


def test_ac4_power_toggle_button():
    """A Power toggle button must be present in the lap chart controls."""
    js = _js()
    assert (
        'data-metric="power"' in js
        or "data-metric='power'" in js
    ), "run-view.js must include a Power toggle button for the lap chart"


def test_ac4_toggle_click_handler():
    """Toggle buttons must have a click event listener that updates the chart metric."""
    js = _js()
    assert "_lapMetric" in js or "lapMetric" in js, (
        "run-view.js must track the active lap metric (e.g. _lapMetric)"
    )
    assert "addEventListener" in js or "onclick" in js, (
        "run-view.js must attach a click handler to the metric toggle buttons"
    )


def test_ac4_active_toggle_styling():
    """The active toggle must receive a visual distinction (rv-mtog--active class)."""
    combined = _combined()
    assert "rv-mtog--active" in combined, (
        "run-view must apply an 'rv-mtog--active' class to the active metric toggle"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC5 — Gradient theme and structure-over-pixel-styling conventions
# ═════════════════════════════════════════════════════════════════════════════

def test_ac5_uses_design_tokens():
    """Page must use CSS custom property tokens (--rv-teal, --card-bg, etc.)."""
    html = _html()
    assert "var(--" in html, (
        "run-view.html must use CSS custom property tokens (var(--...)) "
        "for theming rather than raw pixel values"
    )


def test_ac5_rv_teal_defined():
    """The teal accent variable --rv-teal must be defined for Zone 2 highlights."""
    html = _html()
    assert "--rv-teal" in html, (
        "run-view.html must define --rv-teal for Zone 2 color accents"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC6 — Named constant for Zone 2 HR range; no magic numbers inline
# ═════════════════════════════════════════════════════════════════════════════

def test_ac6_zone2_constants_file_exists():
    """zone2-constants.js must exist as the single source of truth for Zone 2 range."""
    assert _Z2_CONST_PATH.exists(), (
        "frontend/js/zone2-constants.js must exist as the single source of truth "
        "for the Zone 2 HR range constants"
    )


def test_ac6_zone2_min_defined_in_constants():
    """ZONE2_HR_MIN (130) must be defined in zone2-constants.js."""
    z2 = _z2()
    assert "ZONE2_HR_MIN" in z2 and "130" in z2, (
        "zone2-constants.js must define ZONE2_HR_MIN = 130"
    )


def test_ac6_zone2_max_defined_in_constants():
    """ZONE2_HR_MAX (155) must be defined in zone2-constants.js."""
    z2 = _z2()
    assert "ZONE2_HR_MAX" in z2 and "155" in z2, (
        "zone2-constants.js must define ZONE2_HR_MAX = 155"
    )


def test_ac6_run_view_imports_zone2_constants():
    """run-view.html must include zone2-constants.js before run-view.js."""
    html = _html()
    z2_idx = html.find("zone2-constants.js")
    rv_idx = html.find("run-view.js")
    assert z2_idx != -1, "run-view.html must load zone2-constants.js"
    assert rv_idx != -1, "run-view.html must load run-view.js"
    assert z2_idx < rv_idx, (
        "zone2-constants.js must be loaded before run-view.js in run-view.html"
    )


def test_ac6_no_magic_130_in_run_view_js():
    """The magic number 130 (Zone 2 min HR) must NOT appear as a bare literal in
    run-view.js; it must come from ZONE2_HR_MIN."""
    js = _js()
    # 130 must not appear in a comparison context inline — it may appear in comments
    # Remove comment lines first
    no_comments = re.sub(r"//[^\n]*", "", js)
    no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL)
    # Check for >= 130 or <= 130 or === 130 patterns (comparison magic numbers)
    magic_pattern = re.search(r"[><=!]=?\s*130\b", no_comments)
    assert not magic_pattern, (
        "run-view.js must not use 130 as a magic number in comparisons; "
        "use ZONE2_HR_MIN from zone2-constants.js instead"
    )


def test_ac6_no_magic_155_in_run_view_js():
    """The magic number 155 (Zone 2 max HR) must NOT appear as a bare literal in
    run-view.js; it must come from ZONE2_HR_MAX."""
    js = _js()
    no_comments = re.sub(r"//[^\n]*", "", js)
    no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL)
    magic_pattern = re.search(r"[><=!]=?\s*155\b", no_comments)
    assert not magic_pattern, (
        "run-view.js must not use 155 as a magic number in comparisons; "
        "use ZONE2_HR_MAX from zone2-constants.js instead"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC7 — Z2 laps: teal background, Z2 pill in Lap column, teal ring on bar
# ═════════════════════════════════════════════════════════════════════════════

def test_ac7_z2_row_class_defined():
    """The teal row background CSS class rv-lap-row--z2 must be defined."""
    html = _html()
    assert "rv-lap-row--z2" in html, (
        "run-view.html must define the .rv-lap-row--z2 CSS class for Zone 2 "
        "row background (teal tint)"
    )


def test_ac7_z2_row_class_applied():
    """run-view.js must apply rv-lap-row--z2 to rows whose avg_hr is in Zone 2."""
    js = _js()
    assert "rv-lap-row--z2" in js, (
        "run-view.js must apply 'rv-lap-row--z2' to Zone 2 lap rows"
    )


def test_ac7_z2_pill_defined():
    """The Z2 pill CSS class rv-z2-pill must be defined in the page."""
    html = _html()
    assert "rv-z2-pill" in html, (
        "run-view.html must define the .rv-z2-pill CSS class for the Zone 2 pill"
    )


def test_ac7_z2_pill_rendered():
    """run-view.js must render a Z2 pill in the Lap column for Zone 2 laps."""
    js = _js()
    assert "rv-z2-pill" in js and "Z2" in js, (
        "run-view.js must render a Z2 pill (rv-z2-pill class with 'Z2' text) "
        "in the Lap column for laps in the Zone 2 HR range"
    )


def test_ac7_z2_bar_ring_defined():
    """The teal ring CSS class rv-bar--z2 must be defined in the page."""
    html = _html()
    assert "rv-bar--z2" in html, (
        "run-view.html must define the .rv-bar--z2 CSS class for the teal ring "
        "on Zone 2 chart bars"
    )


def test_ac7_z2_bar_ring_applied():
    """run-view.js must apply rv-bar--z2 to chart bars for Zone 2 laps."""
    js = _js()
    assert "rv-bar--z2" in js, (
        "run-view.js must apply the 'rv-bar--z2' class to chart bars whose "
        "lap avg_hr falls in the Zone 2 range"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC8 — Non-Z2 laps: default row style, no Z2 pill
# ═════════════════════════════════════════════════════════════════════════════

def test_ac8_z2_pill_conditionally_rendered():
    """The Z2 pill must be conditionally rendered (not on every lap)."""
    js = _js()
    # The pill must be inside a conditional check for Zone 2
    # Verify the isZ2 (or equivalent) guard exists near the z2-pill usage
    z2_pill_idx = js.find("rv-z2-pill")
    assert z2_pill_idx != -1
    # There should be a conditional (isZ2 or similar) within 500 chars before pill usage
    nearby_before = js[max(0, z2_pill_idx - 500): z2_pill_idx]
    has_condition = (
        "isZ2" in nearby_before
        or "is_z2" in nearby_before
        or "zone2" in nearby_before.lower()
        or "? " in nearby_before
    )
    assert has_condition, (
        "The Z2 pill must be conditionally rendered — only for Zone 2 laps. "
        "A guard (isZ2 or similar) must appear before the pill HTML."
    )


def test_ac8_default_row_style_when_not_z2():
    """Non-Z2 laps must use the default row class (no rv-lap-row--z2)."""
    js = _js()
    # The row class must be conditionally applied
    assert "rv-lap-row" in js, "Lap rows must have the rv-lap-row base class"
    # Must show conditional logic around z2 class
    assert "rowClass" in js or ("isZ2" in js and "rv-lap-row--z2" in js), (
        "The rv-lap-row--z2 class must be applied conditionally, not on all rows"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC9 — Power cell shows dash (—) when power data absent
# ═════════════════════════════════════════════════════════════════════════════

def test_ac9_em_dash_used_for_null():
    """run-view.js must use an em dash (—) for null/absent values."""
    js = _js()
    assert "—" in js or "\\u2014" in js or '"—"' in js or "'—'" in js, (
        "run-view.js must use an em dash (—) to represent absent data values"
    )


def test_ac9_power_dash_function_exists():
    """A dash helper function must be used for null-coalescing to em dash."""
    js = _js()
    # The dash() function or equivalent must exist
    assert "function dash" in js or "dash(" in js, (
        "run-view.js must have a dash() helper (or equivalent) that returns '—' "
        "for null/absent values including power data"
    )


def test_ac9_power_column_uses_dash():
    """The Power column in the lap table must pass avg_power through a null-safe
    function that returns '—' when absent."""
    js = _js()
    # avg_power must appear near a dash() call or null check
    avg_power_idx = js.find("avg_power")
    assert avg_power_idx != -1, "run-view.js must reference avg_power for the Power column"
    nearby = js[avg_power_idx: avg_power_idx + 200]
    has_dash = "dash(" in nearby or "—" in nearby or "null" in nearby
    assert has_dash, (
        "The avg_power value in the Power column must be wrapped in dash() or "
        "null-checked to render '—' when absent"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC10 — Power toggle visible even when no power data; chart renders dashes
# ═════════════════════════════════════════════════════════════════════════════

def test_ac10_power_toggle_always_rendered():
    """The Power toggle button must always be rendered, even when no power data exists.
    The toggle HTML must not be conditional on power data availability."""
    js = _js()
    # The power toggle button must be rendered unconditionally (inside renderLapTable,
    # not behind a hasStryd or power-data check)
    power_toggle_idx = js.find('data-metric="power"')
    if power_toggle_idx == -1:
        power_toggle_idx = js.find("data-metric='power'")
    assert power_toggle_idx != -1, (
        "run-view.js must render a Power metric toggle button"
    )
    # Check that the power toggle is not inside a strydPresent block
    # by looking at the surrounding context — it should be in renderLapTable
    # which is called for all laps regardless of power data
    render_lap_idx = js.find("function renderLapTable")
    assert render_lap_idx != -1, "run-view.js must have a renderLapTable function"
    render_lap_end = js.find("\n  function ", render_lap_idx + 1)
    if render_lap_end == -1:
        render_lap_end = len(js)
    render_lap_body = js[render_lap_idx:render_lap_end]
    assert 'data-metric="power"' in render_lap_body or "data-metric='power'" in render_lap_body, (
        "The Power toggle button must be rendered inside renderLapTable so it "
        "always appears regardless of whether laps have power data"
    )


def test_ac10_chart_handles_all_null_values():
    """When all lap values for the selected metric are null, the chart must not
    simply return empty string — it must render placeholder bars or dashes."""
    js = _js()
    render_lap_chart_idx = js.find("function renderLapChart")
    assert render_lap_chart_idx != -1, "run-view.js must have a renderLapChart function"
    # Find the end of renderLapChart
    brace_start = js.find("{", render_lap_chart_idx)
    depth = 0
    i = brace_start
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    chart_body = js[render_lap_chart_idx: i + 1]
    # The function must NOT return "" when validVals is empty — it must render something
    # Check that it doesn't immediately return empty string when no valid values
    bad_pattern = re.search(r"if\s*\(\s*!validVals\.length\s*\)\s*return\s*['\"]", chart_body)
    assert not bad_pattern, (
        "renderLapChart must not return an empty string when all values are null. "
        "It must render placeholder (zero-height) bars so the chart container "
        "still appears and the Power toggle remains functional."
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC12 — Responsive at mobile breakpoints
# ═════════════════════════════════════════════════════════════════════════════

def test_ac12_table_wrap_overflow_x_auto():
    """The lap table wrapper must have overflow-x: auto for horizontal scrolling
    on narrow viewports."""
    html = _html()
    assert "overflow-x: auto" in html or "overflow-x:auto" in html, (
        "run-view.html must set overflow-x: auto on the lap table wrapper "
        "(.rv-lap-table-wrap) to prevent horizontal overflow on mobile"
    )


def test_ac12_min_width_on_table():
    """The lap table must have a min-width to ensure columns are readable when
    the wrapper scrolls horizontally."""
    html = _html()
    assert "min-width" in html, (
        "run-view.html must set a min-width on the .rv-lap-table to ensure all "
        "columns remain readable via horizontal scroll on narrow viewports"
    )


def test_ac12_mobile_media_query():
    """A @media query must exist to handle mobile layout adjustments."""
    html = _html()
    assert "@media" in html, (
        "run-view.html must include a @media breakpoint rule for mobile/narrow "
        "viewport layout adjustments"
    )
