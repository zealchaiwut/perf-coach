"""Tests for issue #915: Compact run detail view for higher information density.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance Criteria:
  AC1  — Three stacked hero tiles replaced by a single horizontal hero strip;
          Distance, Avg Pace, Duration all display with same labels/formatting.
  AC2  — Load/Intensity grid renders in a fixed 4-column layout with left-aligned,
          tighter tiles (not the previous auto-fill 2-per-row layout).
  AC3  — Variability Index (np / avg_power, 2 dp) in Load grid; — when null/absent.
  AC4  — Decoupling % (from aerobic_decoupling.decoupling_pct) in Load grid;
          — when absent/null; rendered as percentage.
  AC5  — Stryd-sourced metrics retain STRYD pill; Strava-sourced retain STRAVA pill.
  AC6  — Lap table is full-width with table-layout:fixed; all 7 columns visible
          without horizontal scrolling at typical viewport widths.
  AC7  — Zone-2 lap row highlighting preserved.
  AC8  — Pace/HR/Power lap-chart toggle preserved and functional.
  AC9  — Session-profile section, route placeholder, source strip remain present.
  AC10 — Card padding and section-title font sizing are reduced (materially shorter).
  AC11 — No data removed; null/missing values render as — everywhere.
  AC12 — All data from existing GET /api/workouts/{id}/full — no new API calls.
  AC13 — Existing run-view automated tests pass without modification.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RV_HTML_PATH = _ROOT / "frontend" / "pages" / "run-view.html"
_RV_JS_PATH = _ROOT / "frontend" / "js" / "run-view.js"


def _html() -> str:
    assert _RV_HTML_PATH.exists(), f"File not found: {_RV_HTML_PATH}"
    return _RV_HTML_PATH.read_text()


def _js() -> str:
    assert _RV_JS_PATH.exists(), f"File not found: {_RV_JS_PATH}"
    return _RV_JS_PATH.read_text()


def _combined() -> str:
    return _html() + _js()


# ═════════════════════════════════════════════════════════════════════════════
# AC1 — Horizontal hero strip replaces three stacked tiles
# ═════════════════════════════════════════════════════════════════════════════

def test_ac1_hero_strip_class_defined():
    """A CSS class for the hero strip must exist in run-view.html."""
    html = _html()
    assert "rv-hero-strip" in html, (
        "run-view.html must define a .rv-hero-strip CSS class for the "
        "combined horizontal hero strip (AC1)"
    )


def test_ac1_hero_strip_is_flex_row():
    """The hero strip must be a flex row (display:flex) so cells sit side-by-side."""
    html = _html()
    # Find the .rv-hero-strip rule
    strip_idx = html.find("rv-hero-strip")
    assert strip_idx != -1, ".rv-hero-strip CSS block must exist"
    nearby = html[strip_idx: strip_idx + 300]
    assert "flex" in nearby, (
        ".rv-hero-strip must use display:flex so all three cells sit side-by-side (AC1)"
    )


def test_ac1_hero_cells_rendered_in_js():
    """run-view.js must render hero strip cells for Distance, Avg Pace, Duration."""
    js = _js()
    lower = js.lower()
    assert "distance" in lower, "hero strip must include Distance (AC1)"
    assert "pace" in lower, "hero strip must include Avg Pace (AC1)"
    assert "duration" in lower, "hero strip must include Duration (AC1)"


def test_ac1_hero_strip_used_in_hero_section():
    """run-view.js must use the hero strip class in the heroSection."""
    js = _js()
    assert "rv-hero-strip" in js, (
        "run-view.js must render the hero strip via class rv-hero-strip (AC1)"
    )


def test_ac1_hero_section_no_separate_tiles():
    """heroSection in run-view.js must use the hero strip, not three separate
    rv-tile cards placed in rv-hero-row."""
    js = _js()
    # Find the heroSection variable assignment
    hero_idx = js.find("heroSection")
    assert hero_idx != -1, "run-view.js must define a heroSection variable"
    hero_end = js.find(";", hero_idx + 100)
    if hero_end == -1:
        hero_end = hero_idx + 800
    hero_body = js[hero_idx: hero_end]
    # Old pattern used rv-hero-row with multiple tile() calls; new pattern uses strip
    assert "rv-hero-strip" in hero_body, (
        "heroSection must use rv-hero-strip, not the old rv-hero-row with "
        "separate tile() calls (AC1)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC2 — Load grid: fixed 4-column layout, left-aligned tiles
# ═════════════════════════════════════════════════════════════════════════════

def test_ac2_tile_grid_four_column():
    """The rv-tile-grid must use a fixed 4-column layout."""
    html = _html()
    # The grid CSS must specify exactly 4 columns
    assert "repeat(4" in html or "repeat(4," in html, (
        "run-view.html .rv-tile-grid must use grid-template-columns: repeat(4, ...) "
        "for a fixed 4-column layout (AC2)"
    )


def test_ac2_tile_grid_not_auto_fill():
    """The rv-tile-grid must not use auto-fill (the old 2-per-row layout)."""
    html = _html()
    # Look for the rv-tile-grid rule
    grid_idx = html.find("rv-tile-grid")
    assert grid_idx != -1, ".rv-tile-grid rule must be in run-view.html"
    # Find the CSS block for this rule
    block_start = html.rfind("{", 0, grid_idx)
    block_end = html.find("}", grid_idx)
    block = html[block_start: block_end] if block_start != -1 and block_end != -1 else ""
    assert "auto-fill" not in block, (
        ".rv-tile-grid must not use auto-fill; it must be a fixed 4-column grid (AC2)"
    )


def test_ac2_tile_left_aligned():
    """Tiles in the Load grid must be left-aligned (not center-aligned)."""
    html = _html()
    # Find the .rv-tile rule and check text-align
    tile_idx = html.find(".rv-tile {")
    if tile_idx == -1:
        tile_idx = html.find(".rv-tile{")
    assert tile_idx != -1, ".rv-tile rule must exist"
    block_end = html.find("}", tile_idx)
    tile_block = html[tile_idx: block_end] if block_end != -1 else html[tile_idx: tile_idx + 200]
    assert "text-align: center" not in tile_block and "text-align:center" not in tile_block, (
        ".rv-tile must not be center-aligned; tiles should be left-aligned for the "
        "compact 4-column grid layout (AC2)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC3 — Variability Index tile
# ═════════════════════════════════════════════════════════════════════════════

def test_ac3_variability_index_label_present():
    """run-view.js must render a 'Variability' tile in the Load/Intensity grid."""
    js = _js()
    lower = js.lower()
    assert "variab" in lower or "var. index" in lower or "var index" in lower, (
        "run-view.js must render a Variability Index tile in the Load/Intensity grid (AC3)"
    )


def test_ac3_variability_index_computed_from_np_and_avg_power():
    """run-view.js must compute Variability Index as np / avg_power."""
    js = _js()
    assert "np" in js and "avg_power" in js, (
        "run-view.js must reference both 'np' and 'avg_power' to compute "
        "Variability Index (AC3)"
    )
    # Must do division
    assert "/" in js, "run-view.js must divide np by avg_power for Variability Index (AC3)"


def test_ac3_variability_index_rounded_to_2dp():
    """Variability Index must be rounded to two decimal places."""
    js = _js()
    assert "toFixed(2)" in js or "toFixed( 2 )" in js, (
        "run-view.js must use toFixed(2) to round Variability Index to 2 decimal places (AC3)"
    )


def test_ac3_variability_index_dash_when_null():
    """Variability Index must display — when np or avg_power is null/absent."""
    js = _js()
    # Must have a null-guard before computing np/avg_power ratio
    assert "np" in js and ("null" in js or "dash(" in js or "—" in js), (
        "run-view.js must guard against null np or avg_power and render — for "
        "Variability Index (AC3)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC4 — Decoupling % tile
# ═════════════════════════════════════════════════════════════════════════════

def test_ac4_decoupling_label_present():
    """run-view.js must render a Decoupling tile in the Load/Intensity grid."""
    js = _js()
    lower = js.lower()
    assert "decoupling" in lower, (
        "run-view.js must render a Decoupling tile in the Load/Intensity grid (AC4)"
    )


def test_ac4_decoupling_reads_aerobic_decoupling():
    """run-view.js must read decoupling from data.aerobic_decoupling."""
    js = _js()
    assert "aerobic_decoupling" in js, (
        "run-view.js must read data.aerobic_decoupling for the Decoupling % tile (AC4)"
    )


def test_ac4_decoupling_dash_when_absent():
    """Decoupling must render — when absent or null."""
    js = _js()
    # There must be a null check near decoupling usage
    assert "aerobic_decoupling" in js and ("null" in js or "dash(" in js or "—" in js), (
        "run-view.js must render — for Decoupling when absent or null (AC4)"
    )


def test_ac4_decoupling_rendered_as_percentage():
    """Decoupling value must be rendered as a percentage (% suffix)."""
    js = _js()
    # Near the decoupling tile, there must be a % symbol
    dec_idx = js.lower().find("decoupling")
    assert dec_idx != -1
    nearby = js[dec_idx: dec_idx + 400]
    assert "%" in nearby, (
        "Decoupling tile must render a % suffix to show it as a percentage (AC4)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC5 — STRYD and STRAVA pills retained
# ═════════════════════════════════════════════════════════════════════════════

def test_ac5_stryd_pill_class_defined():
    """A CSS class for the STRYD pill must be present in run-view.html."""
    html = _html()
    assert "pill" in html.lower() and "stryd" in html.lower(), (
        "run-view.html must define a pill CSS class for the STRYD source indicator (AC5)"
    )


def test_ac5_stryd_pill_rendered_in_js():
    """run-view.js must render a STRYD pill on Stryd-sourced metric tiles."""
    js = _js()
    assert "STRYD" in js or "stryd" in js.lower(), (
        "run-view.js must render STRYD pills on Stryd-sourced metric tiles (AC5)"
    )
    # Must be inside the intensity section building code
    intensity_idx = js.find("intensitySection")
    assert intensity_idx != -1, "run-view.js must define intensitySection"
    intensity_body = js[intensity_idx: intensity_idx + 1500]
    assert "stryd" in intensity_body.lower() or "STRYD" in intensity_body, (
        "Stryd pill must appear in the intensitySection builder (AC5)"
    )


def test_ac5_strava_pill_rendered_in_js():
    """run-view.js must render a STRAVA pill on Strava-sourced metric tiles.
    The stravaTile helper or STRAVA pill text must appear in the run-view.js
    intensity-building code (which may be in the variable assignments that feed
    into intensitySection rather than in the assignment body itself)."""
    js = _js()
    # The stravaTile function must be defined (proves Strava pill is used)
    assert "stravaTile" in js or "STRAVA" in js, (
        "run-view.js must define a stravaTile helper or render STRAVA pill text "
        "for Strava-sourced metric tiles (AC5)"
    )
    # Strava pill CSS class must be referenced to actually appear in output
    assert "rv-pill--strava" in js, (
        "run-view.js must use rv-pill--strava CSS class for STRAVA source pills (AC5)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC6 — Lap table: full-width, table-layout:fixed, 7 columns always visible
# ═════════════════════════════════════════════════════════════════════════════

def test_ac6_lap_table_fixed_layout():
    """The lap table must use table-layout: fixed."""
    html = _html()
    assert "table-layout: fixed" in html or "table-layout:fixed" in html, (
        "run-view.html .rv-lap-table must use table-layout: fixed so all 7 "
        "columns are visible without horizontal scrolling (AC6)"
    )


def test_ac6_lap_table_full_width():
    """The lap table must span full available width (width: 100%)."""
    html = _html()
    # The rv-lap-table must have width:100%
    lap_table_idx = html.find("rv-lap-table")
    assert lap_table_idx != -1
    # Look for width: 100% near the lap table CSS rule
    rule_end = html.find("}", lap_table_idx)
    rule_block = html[lap_table_idx: rule_end] if rule_end != -1 else html[lap_table_idx: lap_table_idx + 200]
    assert "100%" in rule_block or "width: 100%" in html, (
        "run-view.html .rv-lap-table must use width: 100% so the table fills "
        "the full available width (AC6)"
    )


def test_ac6_no_large_min_width_on_lap_table():
    """The lap table must not have a large min-width that forces horizontal scrolling."""
    html = _html()
    lap_table_idx = html.find(".rv-lap-table {")
    if lap_table_idx == -1:
        lap_table_idx = html.find(".rv-lap-table{")
    if lap_table_idx == -1:
        # Rule may have more selectors - try another approach
        # Search for the CSS block that includes rv-lap-table
        all_occurrences = [m.start() for m in re.finditer(r'\.rv-lap-table\b', html)]
        for occ in all_occurrences:
            block_start = occ
            block_end = html.find("}", block_start)
            block = html[block_start: block_end]
            if "min-width" in block:
                # Extract the min-width value
                mw_match = re.search(r"min-width\s*:\s*(\d+)px", block)
                if mw_match:
                    mw_val = int(mw_match.group(1))
                    assert mw_val < 400, (
                        f"rv-lap-table min-width must be < 400px to avoid horizontal "
                        f"scrolling on mobile; got {mw_val}px (AC6)"
                    )
        return
    block_end = html.find("}", lap_table_idx)
    block = html[lap_table_idx: block_end] if block_end != -1 else ""
    if "min-width" in block:
        mw_match = re.search(r"min-width\s*:\s*(\d+)px", block)
        if mw_match:
            mw_val = int(mw_match.group(1))
            assert mw_val < 400, (
                f"rv-lap-table min-width must be < 400px to avoid forcing horizontal "
                f"scroll on mobile; got {mw_val}px (AC6)"
            )


# ═════════════════════════════════════════════════════════════════════════════
# AC7 — Zone-2 lap row highlighting preserved
# ═════════════════════════════════════════════════════════════════════════════

def test_ac7_z2_row_highlighting_still_present():
    """Zone-2 row highlighting (rv-lap-row--z2) must still be applied in run-view.js."""
    js = _js()
    assert "rv-lap-row--z2" in js, (
        "Zone-2 lap row highlighting (rv-lap-row--z2) must be preserved (AC7)"
    )


def test_ac7_z2_pill_still_rendered():
    """The Z2 pill must still be rendered in the Lap column for Zone 2 laps."""
    js = _js()
    assert "rv-z2-pill" in js and "Z2" in js, (
        "Z2 pill (rv-z2-pill) must be preserved in the lap table (AC7)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC8 — Pace/HR/Power lap-chart toggle preserved
# ═════════════════════════════════════════════════════════════════════════════

def test_ac8_pace_toggle_preserved():
    """Pace toggle must still be present in the lap chart controls."""
    js = _js()
    assert 'data-metric="pace"' in js or "data-metric='pace'" in js, (
        "Pace toggle button must be preserved in the lap chart (AC8)"
    )


def test_ac8_power_toggle_preserved():
    """Power toggle must still be present in the lap chart controls."""
    js = _js()
    assert 'data-metric="power"' in js or "data-metric='power'" in js, (
        "Power toggle button must be preserved in the lap chart (AC8)"
    )


def test_ac8_hr_line_preserved():
    """HR must still be drawn as a line on the lap chart."""
    js = _js()
    assert "rv2-hr-svg" in js and "polyline" in js, (
        "HR lap-chart line (rv2-hr-svg polyline) must be preserved (AC8)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC9 — Session profile, route placeholder, and source strip remain present
# ═════════════════════════════════════════════════════════════════════════════

def test_ac9_session_profile_present():
    """Session profile section must still be rendered in run-view.js."""
    js = _js()
    assert "profileSection" in js, (
        "profileSection (session profile) must remain present in run-view.js (AC9)"
    )
    assert "detected_profile" in js, (
        "Session profile must still read from detected_profile (AC9)"
    )


def test_ac9_route_placeholder_present():
    """Route placeholder must still be rendered."""
    js = _js()
    assert "Map appears once GPS sync is added" in js, (
        'Route placeholder ("Map appears once GPS sync is added") must remain (AC9)'
    )


def test_ac9_source_strip_present():
    """Source strip must still be rendered."""
    js = _js()
    assert "sourceSection" in js or "rv-source-strip" in js, (
        "Source strip section must remain present in run-view.js (AC9)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC10 — Reduced card padding and section-title font size
# ═════════════════════════════════════════════════════════════════════════════

def test_ac10_card_padding_reduced():
    """rv-card padding must be reduced below the previous 20px value."""
    html = _html()
    card_idx = html.find(".rv-card {")
    if card_idx == -1:
        card_idx = html.find(".rv-card{")
    assert card_idx != -1, ".rv-card CSS rule must exist"
    block_end = html.find("}", card_idx)
    card_block = html[card_idx: block_end] if block_end != -1 else html[card_idx: card_idx + 300]
    # Extract the padding value
    padding_match = re.search(r"padding\s*:\s*([\d\s]+)px", card_block)
    if padding_match:
        # First token is top (and possibly the only value for uniform padding)
        first_val = int(padding_match.group(1).split()[0])
        assert first_val < 20, (
            f"rv-card padding must be reduced below 20px; got {first_val}px (AC10)"
        )
    else:
        # Check that 20px padding is gone
        assert "padding: 20px" not in card_block and "padding:20px" not in card_block, (
            "rv-card padding must be reduced below the previous 20px (AC10)"
        )


def test_ac10_section_title_font_size_reduced():
    """rv-section-title font-size must be reduced below 13px."""
    html = _html()
    title_idx = html.find("rv-section-title")
    assert title_idx != -1, ".rv-section-title must be defined in run-view.html"
    block_end = html.find("}", title_idx)
    title_block = html[title_idx: block_end] if block_end != -1 else html[title_idx: title_idx + 200]
    # Extract font-size value
    fs_match = re.search(r"font-size\s*:\s*([\d.]+)px", title_block)
    if fs_match:
        fs_val = float(fs_match.group(1))
        assert fs_val < 13, (
            f"rv-section-title font-size must be reduced below 13px; got {fs_val}px (AC10)"
        )
    else:
        assert "font-size: 13px" not in title_block and "font-size:13px" not in title_block, (
            "rv-section-title font-size must be reduced below the previous 13px (AC10)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# AC11 — No data removed; null → — everywhere
# ═════════════════════════════════════════════════════════════════════════════

def test_ac11_dash_helper_still_present():
    """run-view.js must still have a dash() helper for null → — rendering."""
    js = _js()
    assert "function dash" in js, (
        "run-view.js must retain the dash() helper for null-coalescing to — (AC11)"
    )


def test_ac11_tss_tile_still_present():
    """TSS tile must still be present in the Load/Intensity section."""
    js = _js()
    assert "tss" in js.lower(), (
        "TSS tile must remain in the Load/Intensity section — no data removed (AC11)"
    )


def test_ac11_np_tile_present():
    """NP (Normalized Power) tile must be present in the Load/Intensity grid."""
    combined = _combined()
    assert "np" in combined.lower() or "normalized" in combined.lower(), (
        "NP tile must be present in the Load/Intensity grid (AC11)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC12 — All data from existing /full endpoint, no new API calls
# ═════════════════════════════════════════════════════════════════════════════

def test_ac12_only_full_endpoint_called():
    """run-view.js must only call /full — no new API endpoints introduced.
    The fetch call pattern uses string concatenation so the literal fragment
    '/api/workouts/' is normal; we check that '/full' appears in the fetch
    context and that no entirely new API paths were added."""
    js = _js()
    assert "/full" in js, "run-view.js must call the /full endpoint"
    # Count the number of fetch() calls — must remain exactly 1
    fetch_count = js.count("fetch(")
    assert fetch_count == 1, (
        f"run-view.js must have exactly 1 fetch() call (the /full endpoint); "
        f"found {fetch_count} — no new API calls may be added (AC12)"
    )
